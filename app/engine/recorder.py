"""TickRecorder — atomic per-tick persistence (Phase 6, H9).

All audit + trade rows for one tick are written in a SINGLE ``session_scope``
transaction → all-or-nothing (no partial trading state). The kill-switch HALT is
written separately by ``KillSwitch`` in an independent session, so a rolled-back
tick transaction can never lose the HALT.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.models import AnalystVerdict
from app.database import session_scope
from app.execution.models import ExecutionResult, Intent
from app.execution.repository import PaperExecutionRepository
from app.market_data.models import Symbol
from app.models import (
    ClaudeDecisionRecord,
    NewsRecord,
    PortfolioSnapshotRecord,
    PositionRecord,
    RiskDecisionRecord,
)
from app.news.models import NewsItem
from app.portfolio.models import AccountState, Position, PositionStatus
from app.risk.models import RiskAssessment


class TickRecorder:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory
        self._exec = PaperExecutionRepository(session_factory)

    def _upsert_news(self, session: Session, items: tuple[NewsItem, ...]) -> None:
        for item in items:
            exists = session.scalars(
                select(NewsRecord).where(
                    NewsRecord.source == item.source, NewsRecord.dedup_key == item.dedup_key
                )
            ).first()
            if exists is not None:
                continue
            session.add(
                NewsRecord(
                    source=item.source, source_id=item.source_id, url=item.url,
                    title=item.title, summary=item.summary,
                    published_at=item.published_at, discovered_at=item.discovered_at,
                    ingested_at=item.ingested_at, available_at=item.available_at,
                    processed_at=item.processed_at, availability_known=item.availability_known,
                    affected_assets=json.dumps(list(item.affected_assets)),
                    trust=item.trust, dedup_key=item.dedup_key,
                    news_pipeline_version=item.news_pipeline_version,
                )
            )

    def _add_claude(
        self, session: Session, verdict: AnalystVerdict, symbol: Symbol, decision_time: datetime
    ) -> str:
        # Decision idempotency (E43): identity is (decision_time, symbol) for the
        # single-symbol/single-candidate-per-tick architecture. Reprocessing the
        # same tick returns the existing row instead of duplicating it.
        existing = session.scalars(
            select(ClaudeDecisionRecord).where(
                ClaudeDecisionRecord.decision_time == decision_time,
                ClaudeDecisionRecord.symbol == str(symbol),
            )
        ).first()
        if existing is not None:
            return existing.id
        rec = ClaudeDecisionRecord(
            decision_time=verdict.decision_time, symbol=str(symbol),
            decision=verdict.decision.value if verdict.decision else None,
            action=verdict.action.value,
            confidence=verdict.confidence,
            reason_codes=json.dumps([r.value for r in verdict.reason_codes]),
            affected_assets=json.dumps(list(verdict.affected_assets)),
            event_risk=verdict.event_risk.value if verdict.event_risk else None,
            evidence=json.dumps(list(verdict.evidence)),
            failure=verdict.failure.value, model_class=verdict.model_class,
            model_id=verdict.model_id, prompt_version=verdict.prompt_version,
            ai_analyst_version=verdict.ai_analyst_version,
            news_pipeline_version=verdict.news_pipeline_version,
            processed_at=verdict.processed_at, latency_seconds=verdict.latency_seconds,
        )
        session.add(rec)
        session.flush()
        return rec.id

    def _add_risk(
        self,
        session: Session,
        assessment: RiskAssessment,
        claude_id: str | None,
        symbol: Symbol,
        decision_time: datetime,
    ) -> None:
        # Decision idempotency (E43): identity (decision_time, symbol).
        existing = session.scalars(
            select(RiskDecisionRecord).where(
                RiskDecisionRecord.decision_time == decision_time,
                RiskDecisionRecord.symbol == str(symbol),
            )
        ).first()
        if existing is not None:
            return
        session.add(
            RiskDecisionRecord(
                decision_time=assessment.decision_time,
                symbol=str(assessment.symbol) if assessment.symbol else None,
                decision=assessment.decision.value, reason=assessment.reason.value,
                reason_codes=json.dumps([assessment.reason.value]),
                recomputed_risk_pct=assessment.recomputed_risk_pct,
                exposure_after_pct=assessment.exposure_after_pct,
                evaluated=json.dumps(assessment.evaluated),
                claude_decision_id=claude_id, risk_version=assessment.risk_version,
                config_version=assessment.config_version,
            )
        )

    def _upsert_position(self, session: Session, position: Position, at: datetime) -> None:
        row = session.scalars(
            select(PositionRecord).where(
                PositionRecord.symbol == str(position.symbol),
                PositionRecord.status == PositionStatus.OPEN.value,
            )
        ).first()
        if row is None:
            session.add(
                PositionRecord(
                    symbol=str(position.symbol), direction=position.direction.value,
                    status=position.status.value, quantity=position.quantity,
                    average_entry=position.average_entry, stop_price=position.stop_price,
                    target_price=position.target_price, opened_at=position.opened_at,
                    closed_at=position.closed_at, fees_paid=position.fees_paid,
                    realized_pnl=position.realized_pnl,
                    strategy_version=position.strategy_version, updated_at=at,
                )
            )
            return
        row.status = position.status.value
        row.quantity = position.quantity
        row.average_entry = position.average_entry
        row.stop_price = position.stop_price
        row.target_price = position.target_price
        row.closed_at = position.closed_at
        row.fees_paid = position.fees_paid
        row.realized_pnl = position.realized_pnl
        row.updated_at = at

    def _add_snapshot(
        self,
        session: Session,
        account: AccountState,
        *,
        snapshot_time: datetime,
        equity: Decimal,
        unrealized: Decimal,
    ) -> None:
        session.add(
            PortfolioSnapshotRecord(
                snapshot_time=snapshot_time, cash=account.cash, equity=equity,
                total_exposure=account.total_exposure(),
                realized_pnl_cum=account.realized_pnl_cum, unrealized_pnl=unrealized,
                fees_paid_cum=account.fees_paid_cum, hwm_equity=account.hwm_equity,
                open_positions=json.dumps(
                    [str(p.symbol) for p in account.open_positions]
                ),
            )
        )

    def record_tick(
        self,
        *,
        decision_time: datetime,
        now: datetime,
        symbol: Symbol,
        news_items: tuple[NewsItem, ...] = (),
        verdict: AnalystVerdict | None = None,
        risk_assessment: RiskAssessment | None = None,
        intent: Intent | None = None,
        exec_result: ExecutionResult | None = None,
        affected_position: Position | None = None,
        account_after: AccountState | None = None,
        equity: Decimal | None = None,
        unrealized: Decimal | None = None,
    ) -> None:
        with session_scope(self._sf) as session:
            self._upsert_news(session, news_items)
            claude_id: str | None = None
            if verdict is not None:
                claude_id = self._add_claude(session, verdict, symbol, decision_time)
            if risk_assessment is not None:
                self._add_risk(session, risk_assessment, claude_id, symbol, decision_time)
            if intent is not None and exec_result is not None:
                self._exec.record_execution(session, intent, exec_result, at=now)
            if affected_position is not None:
                self._upsert_position(session, affected_position, now)
            if account_after is not None and equity is not None:
                self._add_snapshot(
                    session, account_after, snapshot_time=decision_time,
                    equity=equity, unrealized=unrealized or Decimal(0),
                )
