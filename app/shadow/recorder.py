"""ShadowRecorder — atomic per-boundary shadow persistence (Phase 8).

Writes ONE boundary's audit in a single ``session_scope`` transaction
(all-or-nothing): the shared audit rows (``news`` / ``claude_decisions`` /
``risk_decisions``) via the frozen P6 ``TickRecorder`` writers (single source of
truth for those row shapes), plus the shadow-only ``shadow_decisions`` row.

It writes **no** operational tables (``paper_orders`` / ``paper_fills`` /
``positions`` / ``portfolio_snapshots``) and calls **no** ledger — there is no
execution path here. Idempotency: a durable ``shadow_decisions`` row for
``(decision_time, symbol)`` short-circuits (check-then-skip) before any write.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.engine.recorder import TickRecorder
from app.market_data.models import Symbol
from app.models import RiskDecisionRecord, ShadowDecisionRecord
from app.shadow import SHADOW_ENGINE_VERSION
from app.shadow.models import ShadowResult


class ShadowRecorder:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory
        # Reuse the FROZEN P6 audit-row writers (news/claude/risk) unchanged.
        self._tick = TickRecorder(session_factory)

    def find_decision_id(self, decision_time: datetime, symbol: Symbol) -> str | None:
        """Return an existing durable shadow decision id, or None (idempotency)."""
        with session_scope(self._sf) as session:
            row = self._existing(session, decision_time, symbol)
            return row.id if row is not None else None

    @staticmethod
    def _existing(
        session: Session, decision_time: datetime, symbol: Symbol
    ) -> ShadowDecisionRecord | None:
        return session.scalars(
            select(ShadowDecisionRecord).where(
                ShadowDecisionRecord.decision_time == decision_time,
                ShadowDecisionRecord.symbol == str(symbol),
            )
        ).first()

    def record(self, result: ShadowResult, *, shadow_run_id: str | None = None) -> str:
        """Persist one boundary's shadow decision + shared audit rows (atomic).

        Returns the ``shadow_decisions`` row id (existing id if already durable).
        """
        with session_scope(self._sf) as session:
            existing = self._existing(session, result.decision_time, result.symbol)
            if existing is not None:
                return existing.id  # idempotent: never a duplicate durable decision

            # Shared audit rows via the frozen P6 writers (single source of truth).
            self._tick._upsert_news(session, result.news_items)
            claude_id: str | None = None
            if result.verdict is not None:
                claude_id = self._tick._add_claude(
                    session, result.verdict, result.symbol, result.decision_time
                )
            risk_id: str | None = None
            if result.risk_assessment is not None:
                self._tick._add_risk(
                    session, result.risk_assessment, claude_id,
                    result.symbol, result.decision_time,
                )
                risk_row = session.scalars(
                    select(RiskDecisionRecord).where(
                        RiskDecisionRecord.decision_time == result.decision_time,
                        RiskDecisionRecord.symbol == str(result.symbol),
                    )
                ).first()
                risk_id = risk_row.id if risk_row is not None else None

            row = ShadowDecisionRecord(
                decision_time=result.decision_time,
                symbol=str(result.symbol),
                shadow_run_id=shadow_run_id,
                outcome=result.outcome.value,
                stage=result.stage,
                reason=result.reason,
                claude_decision_id=claude_id,
                risk_decision_id=risk_id,
                regime=result.regime,
                market_summary=json.dumps(result.market_summary),
                features_summary=json.dumps(result.features_summary),
                hyp_side=result.hyp_side,
                hyp_quantity=result.hyp_quantity,
                hyp_entry_ref=result.hyp_entry_ref,
                hyp_stop_price=result.hyp_stop_price,
                hyp_target_price=result.hyp_target_price,
                hyp_fill_price=result.hyp_fill_price,
                hyp_fill_fee=result.hyp_fill_fee,
                hyp_fill_state=result.hyp_fill_state,
                engine_version=SHADOW_ENGINE_VERSION,
                indicator_set_version=result.indicator_set_version,
                strategy_version=result.strategy_version,
            )
            session.add(row)
            session.flush()
            return row.id
