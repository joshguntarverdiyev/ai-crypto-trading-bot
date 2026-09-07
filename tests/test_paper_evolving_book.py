"""P9 evolving paper book: entry/exit, fee-exact accounting identity, idempotency."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from app.database import session_scope
from app.models import (
    PaperDecisionRecord,
    PaperOrderRecord,
    PortfolioSnapshotRecord,
    PositionRecord,
)
from app.paper import metrics
from app.paper.store import make_run_session_factory
from tests._p6_helpers import build_1h_raw_with_crash, decision_now, exit_decision_time
from tests._p9_helpers import APPROVE, VETO, build_paper


def _count(sf, model) -> int:
    with session_scope(sf) as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


def test_entry_then_exit_and_accounting_identity(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    assert runner.run_once(decision_now())[0].outcome.value == "trade"
    assert runner.run_once(exit_decision_time())[0].outcome.value == "exit"

    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    # position closed; one order for entry + one for exit
    assert _count(run_sf, PositionRecord) == 1  # single row, now CLOSED
    with session_scope(run_sf) as s:
        assert s.scalars(select(PositionRecord)).first().status == "closed"
        assert _count(run_sf, PaperOrderRecord) == 2

    trades = metrics.reconstruct_trades(run_sf)
    view = metrics.build_view(run_sf, starting_equity=cfg.starting_equity, primary_tf_seconds=3600)
    assert len(trades) == 1
    # Fee-exact accounting identity (fully closed ⇒ no open/unrealized):
    #   ending_equity - starting_equity == Σ closed net_pnl
    assert view.ending_equity - cfg.starting_equity == sum(
        (t.net_pnl for t in trades), Decimal(0)
    )


def test_trade_net_pnl_includes_both_fees(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    runner.run_once(decision_now())
    runner.run_once(exit_decision_time())
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    trades = metrics.reconstruct_trades(run_sf)
    # gross excludes fees; net includes both entry+exit fees ⇒ net strictly < gross.
    assert trades[0].net_pnl < trades[0].gross_pnl


def test_consolidated_snapshot_is_authoritative_latest(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    runner.run_once(decision_now())  # a TRADE boundary → per-tick + consolidated snapshot
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    with session_scope(run_sf) as s:
        snaps = s.scalars(
            select(PortfolioSnapshotRecord).order_by(PortfolioSnapshotRecord.snapshot_time)
        ).all()
        # the LAST snapshot (consolidated) has snapshot_time strictly after decision_time
        from app.time_utils import ensure_utc
        assert ensure_utc(snaps[-1].snapshot_time) > decision_now()


def test_veto_holds_no_trade(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path, analyst_response=VETO)
    out = runner.run_once(decision_now())
    assert out[0].outcome.value == "hold"
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    assert _count(run_sf, PositionRecord) == 0


def test_idempotent_boundary_no_duplicate(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path, analyst_response=APPROVE)
    runner.run_once(decision_now())
    runner.run_once(decision_now())  # same boundary again → idempotent skip
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    # exactly one decision per (decision_time, symbol)
    assert _count(run_sf, PaperDecisionRecord) == 1
