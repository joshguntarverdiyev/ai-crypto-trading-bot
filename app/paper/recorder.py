"""PaperRecorder — per-boundary P9 audit + consolidated equity snapshot (run DB).

Writes into the run's OWN database (per-run isolation). The frozen P6
``TradingEngine`` already persists the operational rows (orders/fills/positions/
per-tick snapshots + shared claude/risk/news audit) atomically inside
``process_tick``. This recorder adds:

* a per-boundary ``paper_decisions`` audit row (idempotency accelerator, gap
  detector, Shadow↔Paper comparison substrate), linking to the same-DB shared
  audit rows and any realized order; and
* ONE **consolidated** end-of-boundary ``portfolio_snapshots`` row valued with the
  FULL multi-symbol decision-time marks (the authoritative equity-curve point),
  with ``snapshot_time`` strictly after ``decision_time`` so it deterministically
  wins ``PortfolioStore.load_account``'s "latest snapshot" query (§35.6).

A ``db_healthy`` probe lets the runner refuse HALTED protective exits when
persistence is unavailable (no phantom exits — §35.2). No live execution path.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.engine.recorder import TickRecorder
from app.market_data.models import Symbol
from app.models import (
    ClaudeDecisionRecord,
    PaperDecisionRecord,
    PaperOrderRecord,
    RiskDecisionRecord,
)
from app.paper import PAPER_ENGINE_VERSION
from app.portfolio import ledger
from app.portfolio.store import PortfolioStore
from app.time_utils import ensure_utc


class PaperRecorder:
    def __init__(
        self, run_session_factory: sessionmaker[Session], starting_equity: Decimal
    ) -> None:
        self._sf = run_session_factory
        self._tick = TickRecorder(run_session_factory)
        self._pf = PortfolioStore(run_session_factory, starting_equity)

    # --- health probe (§35.2) ------------------------------------------
    def db_healthy(self) -> bool:
        try:
            with session_scope(self._sf) as session:
                session.execute(select(PaperDecisionRecord.id).limit(1)).first()
            return True
        except Exception:
            return False

    # --- idempotency ---------------------------------------------------
    def find_decision_id(self, decision_time: datetime, symbol: Symbol) -> str | None:
        with session_scope(self._sf) as session:
            row = self._existing(session, decision_time, symbol)
            return row.id if row is not None else None

    @staticmethod
    def _existing(
        session: Session, decision_time: datetime, symbol: Symbol
    ) -> PaperDecisionRecord | None:
        return session.scalars(
            select(PaperDecisionRecord).where(
                PaperDecisionRecord.decision_time == decision_time,
                PaperDecisionRecord.symbol == str(symbol),
            )
        ).first()

    # --- consolidated end-of-boundary snapshot (§35.6) -----------------
    def record_consolidated_snapshot(
        self, *, marks: dict[str, Decimal], snapshot_time: datetime, decision_time: datetime
    ) -> tuple[Decimal, float | None]:
        """Write the authoritative equity-curve point valued with FULL marks.

        Returns (equity, exposure_after_pct). ``snapshot_time`` is forced strictly
        after ``decision_time`` so this snapshot wins the latest-snapshot query.
        """
        decision_time = ensure_utc(decision_time)
        snapshot_time = ensure_utc(snapshot_time)
        if snapshot_time <= decision_time:
            snapshot_time = decision_time + timedelta(microseconds=1)
        account = self._pf.load_account()
        equity = account.equity(marks)
        account = ledger.with_hwm(account, equity)
        unrealized = account.unrealized_pnl(marks)
        exposure = account.total_exposure()
        exposure_pct = float(exposure / equity) if equity > 0 else None
        with session_scope(self._sf) as session:
            self._tick._add_snapshot(
                session, account, snapshot_time=snapshot_time, equity=equity, unrealized=unrealized
            )
        return equity, exposure_pct

    # --- per-boundary paper decision -----------------------------------
    def record_decision(
        self,
        *,
        run_id: str,
        decision_time: datetime,
        symbol: Symbol,
        outcome: str,
        stage: str,
        reason: str,
        mark: Decimal | None = None,
        regime: str | None = None,
        equity_after: Decimal | None = None,
        exposure_after_pct: float | None = None,
        indicator_set_version: str = "",
        strategy_version: str = "",
    ) -> str:
        """Persist ONE ``paper_decisions`` row (idempotent on ``(decision_time, symbol)``).

        Links to the same-DB shared audit rows and any realized order. ``paper_run_id``
        is stamped with the run identity (run-identity invariant — §35.1).
        """
        with session_scope(self._sf) as session:
            existing = self._existing(session, decision_time, symbol)
            if existing is not None:
                return existing.id  # idempotent: never a duplicate durable decision

            claude_id = self._lookup_id(session, ClaudeDecisionRecord, decision_time, symbol)
            risk_id = self._lookup_id(session, RiskDecisionRecord, decision_time, symbol)
            intent_id = self._lookup_intent_id(session, decision_time, symbol)

            market_summary = {str(symbol): str(mark)} if mark is not None else {}
            row = PaperDecisionRecord(
                paper_run_id=run_id,
                decision_time=decision_time,
                symbol=str(symbol),
                outcome=outcome,
                stage=stage,
                reason=reason,
                claude_decision_id=claude_id,
                risk_decision_id=risk_id,
                intent_id=intent_id,
                regime=regime,
                market_summary=json.dumps(market_summary),
                features_summary="{}",
                equity_after=equity_after,
                exposure_after_pct=exposure_after_pct,
                engine_version=PAPER_ENGINE_VERSION,
                indicator_set_version=indicator_set_version,
                strategy_version=strategy_version,
            )
            session.add(row)
            session.flush()
            return row.id

    @staticmethod
    def _lookup_id(session: Session, model, decision_time: datetime, symbol: Symbol) -> str | None:
        row = session.scalars(
            select(model).where(
                model.decision_time == decision_time, model.symbol == str(symbol)
            )
        ).first()
        return row.id if row is not None else None

    @staticmethod
    def _lookup_intent_id(
        session: Session, decision_time: datetime, symbol: Symbol
    ) -> str | None:
        row = session.scalars(
            select(PaperOrderRecord)
            .where(
                PaperOrderRecord.decision_time == decision_time,
                PaperOrderRecord.symbol == str(symbol),
            )
            .order_by(PaperOrderRecord.created_at.desc())
            .limit(1)
        ).first()
        return row.intent_id if row is not None else None
