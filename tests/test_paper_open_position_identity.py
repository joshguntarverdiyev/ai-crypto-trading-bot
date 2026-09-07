"""P9 accounting identity WITH an open position at the boundary (§35.5)."""

from __future__ import annotations

from sqlalchemy import select

from app.database import session_scope
from app.models import PaperFillRecord, PaperOrderRecord, PortfolioSnapshotRecord, PositionRecord
from app.paper import metrics
from app.paper.store import make_run_session_factory
from tests._p6_helpers import decision_now
from tests._p9_helpers import APPROVE, build_paper


def test_open_position_accounting_identity(tmp_path) -> None:
    # Normal (no-crash) series ⇒ one entry that stays OPEN after a single boundary.
    runner, run_id, main_sf, settings = build_paper(tmp_path, analyst_response=APPROVE)
    assert runner.run_once(decision_now())[0].outcome.value == "trade"

    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)

    # No CLOSED trades yet (the position is still open).
    assert metrics.reconstruct_trades(run_sf) == []

    with session_scope(run_sf) as s:
        pos = s.scalars(
            select(PositionRecord).where(PositionRecord.status == "open")
        ).first()
        assert pos is not None
        snap = s.scalars(
            select(PortfolioSnapshotRecord)
            .order_by(PortfolioSnapshotRecord.snapshot_time.desc()).limit(1)
        ).first()
        buy = s.scalars(
            select(PaperOrderRecord).where(PaperOrderRecord.side == "buy")
        ).first()
        entry_fill = s.scalars(
            select(PaperFillRecord).where(PaperFillRecord.order_id == buy.id)
        ).first()

    # Exit fees do not exist for an open position: fees_paid == the single entry fee.
    assert pos.fees_paid == entry_fill.fee

    # Identity (§35.5), open-position form:
    #   ending_equity - starting_equity
    #     == Σ closed net_pnl (0) + unrealized(open) - entry_fees_of_still_open
    # The consolidated snapshot stores equity and unrealized_pnl valued at the
    # decision-time marks; cash already reflects the entry fee exactly once.
    assert snap.equity - cfg.starting_equity == snap.unrealized_pnl - pos.fees_paid
