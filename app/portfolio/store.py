"""PortfolioStore — DB-authoritative reads + restart rebuild (Phase 6).

The database is the source of truth; ``load_account`` rebuilds the in-memory
``AccountState`` from persisted positions + the latest snapshot (H11). UTC
day/week baselines and the drawdown HWM are reconstructed from snapshots so they
survive restart and never silently reset (H4/H5). Writes are performed atomically
by the engine's recorder (H9), not here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.market_data.models import Symbol
from app.models import PortfolioSnapshotRecord, PositionRecord
from app.portfolio.models import AccountState, Position, PositionStatus
from app.strategy.models import SignalDirection
from app.time_utils import ensure_utc


def day_start(dt: datetime) -> datetime:
    dt = ensure_utc(dt)
    return datetime(dt.year, dt.month, dt.day, tzinfo=UTC)


def week_start(dt: datetime) -> datetime:
    d = day_start(dt)
    return d - timedelta(days=d.weekday())  # Monday 00:00Z (ISO week)


def _to_position(row: PositionRecord) -> Position:
    return Position(
        symbol=Symbol.parse(row.symbol),
        direction=SignalDirection(row.direction),
        status=PositionStatus(row.status),
        quantity=row.quantity,
        average_entry=row.average_entry,
        stop_price=row.stop_price,
        target_price=row.target_price,
        opened_at=ensure_utc(row.opened_at),
        closed_at=ensure_utc(row.closed_at) if row.closed_at else None,
        fees_paid=row.fees_paid,
        realized_pnl=row.realized_pnl,
        strategy_version=row.strategy_version,
    )


class PortfolioStore:
    def __init__(
        self, session_factory: sessionmaker[Session], starting_equity: Decimal
    ) -> None:
        self._sf = session_factory
        self._start = starting_equity

    def load_account(self) -> AccountState:
        with session_scope(self._sf) as session:
            open_rows = session.scalars(
                select(PositionRecord).where(PositionRecord.status == PositionStatus.OPEN.value)
            ).all()
            positions = tuple(_to_position(r) for r in open_rows)
            snap = session.scalars(
                select(PortfolioSnapshotRecord)
                .order_by(PortfolioSnapshotRecord.snapshot_time.desc())
                .limit(1)
            ).first()
            if snap is None:
                return AccountState(
                    cash=self._start, open_positions=positions,
                    realized_pnl_cum=Decimal(0), fees_paid_cum=Decimal(0),
                    hwm_equity=self._start,
                )
            return AccountState(
                cash=snap.cash, open_positions=positions,
                realized_pnl_cum=snap.realized_pnl_cum, fees_paid_cum=snap.fees_paid_cum,
                hwm_equity=snap.hwm_equity,
            )

    def baseline_equity(self, period_start: datetime) -> Decimal:
        """Carry-forward equity baseline for a UTC period (H4 / D1 fix).

        The baseline for a day/week is the equity as it stood **at the period
        boundary** = the latest authoritative snapshot **strictly before**
        ``period_start`` (carried forward). If no prior snapshot exists, the
        configured starting equity. A snapshot *inside* the period is never used
        as the baseline — doing so would exclude that period's own losses from
        the daily/weekly loss limit.
        """
        period_start = ensure_utc(period_start)
        with session_scope(self._sf) as session:
            before = session.scalars(
                select(PortfolioSnapshotRecord)
                .where(PortfolioSnapshotRecord.snapshot_time < period_start)
                .order_by(PortfolioSnapshotRecord.snapshot_time.desc())
                .limit(1)
            ).first()
            return before.equity if before is not None else self._start
