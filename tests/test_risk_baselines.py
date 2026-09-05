"""D1 regression: daily/weekly loss baseline is a carry-forward (pre-period)
snapshot, so a losing first trade inside the period is fully counted; and the
baseline is not reset by restart. Covers both UTC-day and ISO-week boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.database import init_db, make_engine, make_session_factory, session_scope
from app.models import PortfolioSnapshotRecord
from app.portfolio.store import PortfolioStore, day_start, week_start

START = Decimal("10000")


def _sf(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/base.db")
    init_db(engine)
    return make_session_factory(engine)


def _snapshot(sf, *, when: datetime, equity: Decimal) -> None:
    with session_scope(sf) as s:
        s.add(
            PortfolioSnapshotRecord(
                snapshot_time=when, cash=equity, equity=equity,
                total_exposure=Decimal("0"), realized_pnl_cum=Decimal("0"),
                unrealized_pnl=Decimal("0"), fees_paid_cum=Decimal("0"),
                hwm_equity=equity, open_positions="[]",
            )
        )


def test_daily_baseline_is_pre_boundary_carry_forward(tmp_path) -> None:
    sf = _sf(tmp_path)
    store = PortfolioStore(sf, START)
    # Equity at end of the previous day (before the boundary).
    _snapshot(sf, when=datetime(2026, 1, 1, 23, 0, tzinfo=UTC), equity=Decimal("10000"))
    # First trade INSIDE the day loses money -> snapshot at 10:00 with 9000.
    _snapshot(sf, when=datetime(2026, 1, 2, 10, 0, tzinfo=UTC), equity=Decimal("9000"))

    dt = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    baseline = store.baseline_equity(day_start(dt))
    # MUST be the pre-boundary 10000, NOT the in-period 9000 (else the first
    # trade's loss would be excluded from the daily limit).
    assert baseline == Decimal("10000")
    day_loss = float((baseline - Decimal("9000")) / baseline)
    assert day_loss == 0.10  # full 10% loss counted, not 0%


def test_weekly_baseline_is_pre_boundary_carry_forward(tmp_path) -> None:
    sf = _sf(tmp_path)
    store = PortfolioStore(sf, START)
    # 2026-01-05 is a Monday (ISO week start). Snapshot the prior Sunday.
    _snapshot(sf, when=datetime(2026, 1, 4, 20, 0, tzinfo=UTC), equity=Decimal("10000"))
    _snapshot(sf, when=datetime(2026, 1, 6, 9, 0, tzinfo=UTC), equity=Decimal("9400"))
    dt = datetime(2026, 1, 7, 12, 0, tzinfo=UTC)
    assert week_start(dt) == datetime(2026, 1, 5, tzinfo=UTC)
    assert store.baseline_equity(week_start(dt)) == Decimal("10000")


def test_no_prior_snapshot_uses_starting_equity(tmp_path) -> None:
    sf = _sf(tmp_path)
    store = PortfolioStore(sf, START)
    # Only an in-period snapshot exists → still fall back to starting equity,
    # never the in-period snapshot.
    _snapshot(sf, when=datetime(2026, 1, 2, 10, 0, tzinfo=UTC), equity=Decimal("9000"))
    dt = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    assert store.baseline_equity(day_start(dt)) == START


def test_baseline_survives_restart(tmp_path) -> None:
    sf = _sf(tmp_path)
    _snapshot(sf, when=datetime(2026, 1, 1, 23, 0, tzinfo=UTC), equity=Decimal("10000"))
    _snapshot(sf, when=datetime(2026, 1, 2, 10, 0, tzinfo=UTC), equity=Decimal("9000"))
    dt = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    # "restart": a fresh store over the same DB reconstructs the same baseline.
    assert PortfolioStore(sf, START).baseline_equity(day_start(dt)) == Decimal("10000")
    assert PortfolioStore(sf, START).baseline_equity(day_start(dt)) == Decimal("10000")
