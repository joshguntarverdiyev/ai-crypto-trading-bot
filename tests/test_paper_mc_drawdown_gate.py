"""P9 Monte-Carlo max-drawdown ceiling gate (§35.4) — objective, pre-registered."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.paper import metrics
from app.paper.metrics import monte_carlo_drawdown_status, preregistration
from app.paper.store import make_run_session_factory
from backtesting.robustness import MonteCarloDrawdown, monte_carlo_max_drawdown
from backtesting.walkforward import PreRegistrationError, assert_thresholds_preregistered
from tests._p6_helpers import build_1h_raw_with_crash, decision_now, exit_decision_time
from tests._p9_helpers import APPROVE, build_paper, paper_settings


def _mc(p95: float) -> MonteCarloDrawdown:
    return MonteCarloDrawdown(seed=1, iterations=10, p50=p95, p95=p95, p99=p95, worst=p95)


def test_below_ceiling_passes() -> None:
    assert monte_carlo_drawdown_status(_mc(0.10), ceiling=0.25)[0] == "pass"


def test_above_ceiling_fails() -> None:
    assert monte_carlo_drawdown_status(_mc(0.40), ceiling=0.25)[0] == "fail"


def test_insufficient_data() -> None:
    assert monte_carlo_drawdown_status(None, ceiling=0.25)[0] == "insufficient_data"


def test_deterministic_repeated_evaluation() -> None:
    # The underlying MC statistic is seeded/deterministic, so the gate is too.
    pnls = [Decimal(str(x)) for x in [5, -2, 3, -4, 1, -3, 2, -1]]
    mc1 = monte_carlo_max_drawdown(pnls, Decimal("10000"), seed=12345)
    mc2 = monte_carlo_max_drawdown(pnls, Decimal("10000"), seed=12345)
    assert mc1 == mc2
    assert monte_carlo_drawdown_status(mc1, ceiling=0.25) == monte_carlo_drawdown_status(
        mc2, ceiling=0.25
    )


def test_post_registration_ceiling_change_raises(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path)
    prereg = preregistration(run_id, settings.paper_validation_config())
    assert "mc_max_drawdown_ceiling" in prereg.thresholds  # locked before results
    tampered = {**prereg.thresholds, "mc_max_drawdown_ceiling": 0.9}
    with pytest.raises(PreRegistrationError):
        assert_thresholds_preregistered(prereg, tampered)


def test_ceiling_is_part_of_prereg_digest(tmp_path) -> None:
    s1 = paper_settings(tmp_path / "a", paper_mc_max_drawdown_ceiling=0.25)
    s2 = paper_settings(tmp_path / "b", paper_mc_max_drawdown_ceiling=0.15)
    d1 = preregistration("run-x", s1.paper_validation_config()).digest
    d2 = preregistration("run-x", s2.paper_validation_config()).digest
    assert d1 != d2  # changing the ceiling changes the pre-registration digest


def test_gate_wired_into_evaluate(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    runner.run_once(decision_now())
    runner.run_once(exit_decision_time())
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    ev = metrics.evaluate(run_sf, cfg, run_id)
    names = {g.name for g in ev.gates}
    assert "monte_carlo_drawdown_ceiling" in names
    # MC drawdown + bootstrap remain available as (necessary-not-sufficient) evidence.
    assert ev.monte_carlo_drawdown is not None or ev.metrics.trade_count < 2
    assert hasattr(ev, "bootstrap")
