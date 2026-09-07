"""P9 deterministic replay: identical inputs converge to identical durable state."""

from __future__ import annotations

from sqlalchemy import func, select

from app.database import session_scope
from app.models import PaperOrderRecord
from app.paper import metrics
from app.paper.store import make_run_session_factory
from tests._p6_helpers import build_1h_raw_with_crash, decision_now, exit_decision_time
from tests._p9_helpers import APPROVE, build_paper


def _run_full(tmp) -> tuple:
    runner, run_id, main_sf, settings = build_paper(
        tmp, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    runner.run_once(decision_now())
    runner.run_once(exit_decision_time())
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    view = metrics.build_view(run_sf, starting_equity=cfg.starting_equity, primary_tf_seconds=3600)
    trades = metrics.reconstruct_trades(run_sf)
    with session_scope(run_sf) as s:
        orders = s.scalar(select(func.count()).select_from(PaperOrderRecord)) or 0
    return view.ending_equity, tuple(t.net_pnl for t in trades), orders


def test_two_independent_runs_converge(tmp_path) -> None:
    a = _run_full(tmp_path / "a")
    b = _run_full(tmp_path / "b")
    assert a == b  # identical ending equity, trade net_pnls, and order count
