"""P9 objective, pre-registered validation gates + evidence set."""

from __future__ import annotations

import pytest

from app.paper import metrics
from app.paper.store import make_run_session_factory
from backtesting.walkforward import PreRegistrationError, assert_thresholds_preregistered
from tests._p6_helpers import build_1h_raw_with_crash, decision_now, exit_decision_time
from tests._p9_helpers import APPROVE, build_paper


def test_prereg_digest_deterministic(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path)
    cfg = settings.paper_validation_config()
    d1 = metrics.preregistration(run_id, cfg).digest
    d2 = metrics.preregistration(run_id, cfg).digest
    assert d1 == d2


def test_posthoc_threshold_change_rejected(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path)
    prereg = metrics.preregistration(run_id, settings.paper_validation_config())
    tampered = {**prereg.thresholds, "min_meaningful_trades": 5.0}
    with pytest.raises(PreRegistrationError):
        assert_thresholds_preregistered(prereg, tampered)


def test_gates_are_objective_on_small_run(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    runner.run_once(decision_now())
    runner.run_once(exit_decision_time())
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    ev = metrics.evaluate(run_sf, cfg, run_id)
    status = {g.name: g.status for g in ev.gates}
    assert ev.metrics.trade_count == 1
    assert status["meaningful_trades"] == "fail"  # 1 < 100 (operational floor, not significance)
    assert status["operational_duration"] == "fail"  # far below the 90-day floor
    # "observed once" never counts as coverage (regime labels not recorded in v1)
    assert status["regime_coverage"] == "insufficient_data"
    assert len(ev.prereg_digest) == 64


def test_no_profitability_gate_is_a_single_number(tmp_path) -> None:
    # There is no gate that approves a run from one metric; every gate is a named,
    # objective check and statistical gates are 'evidence readiness', not significance.
    runner, run_id, main_sf, settings = build_paper(tmp_path)
    runner.run_once(decision_now())
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    ev = metrics.evaluate(run_sf, cfg, run_id)
    assert {"operational_duration", "meaningful_trades", "regime_coverage"} <= {
        g.name for g in ev.gates
    }
