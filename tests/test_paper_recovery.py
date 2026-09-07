"""P9 failure-injected recovery convergence (§35.12).

A clean run and a run that suffers a RECOVERABLE failure (a crash that lost the
per-boundary decision marker AFTER the tick's operational rows committed, followed
by a restart/takeover) must converge to identical durable accounting. Recovery
never fabricates state; re-processing is at-most-once for durable effects
(intent_id idempotency) while external calls are at-least-once.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.database import session_scope
from app.models import PaperDecisionRecord, PaperOrderRecord, PaperTradingRunRecord
from app.paper import metrics
from app.paper.store import make_run_session_factory, release_run_lock
from app.time_utils import utc_now
from tests._p6_helpers import build_1h_raw_with_crash, decision_now, exit_decision_time
from tests._p9_helpers import APPROVE, build_paper, main_factory, paper_settings


def _durable_state(cfg, run_id) -> tuple:
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    view = metrics.build_view(run_sf, starting_equity=cfg.starting_equity, primary_tf_seconds=3600)
    trades = metrics.reconstruct_trades(run_sf)
    with session_scope(run_sf) as s:
        orders = s.scalar(select(func.count()).select_from(PaperOrderRecord)) or 0
    return (view.ending_equity, tuple(t.net_pnl for t in trades), orders)


def _clean(tmp_path) -> tuple:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    runner.run_once(decision_now())
    runner.run_once(exit_decision_time())
    return _durable_state(settings.paper_validation_config(), run_id)


def _injected(tmp_path) -> tuple:
    settings = paper_settings(tmp_path)
    main_sf = main_factory(settings)
    cfg = settings.paper_validation_config()

    runner_a, run_id, _sf, _s = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash(),
        settings=settings, main_sf=main_sf,
    )
    runner_a.run_once(decision_now())  # entry committed (order/position) + decision marker

    # Simulate a crash that lost ONLY the decision marker (operational rows durable).
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    with session_scope(run_sf) as s:
        row = s.scalars(
            select(PaperDecisionRecord).where(
                PaperDecisionRecord.decision_time == decision_now(),
                PaperDecisionRecord.symbol == "BTC/USDT",
            )
        ).first()
        s.delete(row)

    # Restart / takeover: release the lock and age the heartbeat, then resume.
    release_run_lock(runner_a._lock)
    with session_scope(main_sf) as s:
        cat = s.get(PaperTradingRunRecord, run_id)
        cat.heartbeat_at = utc_now() - timedelta(
            seconds=cfg.owner_stale_intervals * cfg.primary_timeframe.seconds + 3600
        )
    runner_b, _rid, _sf2, _s2 = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash(),
        run_id=run_id, settings=settings, main_sf=main_sf,
    )
    # Re-process the entry boundary (marker was lost): must NOT double-enter, then exit.
    runner_b.run_once(decision_now())
    runner_b.run_once(exit_decision_time())
    return _durable_state(cfg, run_id)


def test_recoverable_failure_converges_to_clean_state(tmp_path) -> None:
    clean = _clean(tmp_path / "clean")
    injected = _injected(tmp_path / "inj")
    assert injected == clean  # identical ending equity, trade net_pnls, and order count
