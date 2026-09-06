"""Metrics + statistics + robustness + walk-forward + benchmark (Phase 7)."""

from __future__ import annotations

from decimal import Decimal

from app.config import load_settings
from app.market_data.models import Symbol
from backtesting.benchmark import buy_and_hold
from backtesting.config import BacktestConfig
from backtesting.metrics import compute_metrics
from backtesting.robustness import (
    monte_carlo_expectancy,
    monte_carlo_max_drawdown,
    trade_removal_curve,
)
from backtesting.statistics import (
    bootstrap_mean_ci,
    lag1_autocorrelation,
    outlier_dependence,
)
from backtesting.walkforward import (
    PreRegistration,
    PreRegistrationError,
    assert_thresholds_preregistered,
    chronological_split,
    walk_forward,
)
from tests.fixtures.backtest_data import (
    build_dataset,
    permissive_risk_config,
    permissive_sizing_config,
    run_fixture_backtest,
    small_indicator_config,
)


def _settings():
    return load_settings(_env_file=None, environment="test")


def test_metrics_are_computed_and_flag_small_samples() -> None:
    settings = _settings()
    result = run_fixture_backtest(build_dataset(), settings)
    m = compute_metrics(result, min_operational_trades=10_000)
    assert m.trade_count == len(result.trades)
    assert m.sample_below_min is True  # operational floor, not significance
    assert m.max_drawdown >= 0.0


def test_bootstrap_is_deterministic_under_seed() -> None:
    settings = _settings()
    result = run_fixture_backtest(build_dataset(), settings)
    nets = [float(p) for p in result.net_pnls]
    a = bootstrap_mean_ci(nets, seed=42, iterations=500)
    b = bootstrap_mean_ci(nets, seed=42, iterations=500)
    assert a == b
    assert a.ci_low <= a.point_estimate <= a.ci_high


def test_monte_carlo_and_outlier_are_deterministic() -> None:
    settings = _settings()
    result = run_fixture_backtest(build_dataset(), settings)
    nets = [float(p) for p in result.net_pnls]
    dd1 = monte_carlo_max_drawdown(nets, 10000.0, seed=7, iterations=200)
    dd2 = monte_carlo_max_drawdown(nets, 10000.0, seed=7, iterations=200)
    assert dd1 == dd2
    exp1 = monte_carlo_expectancy(nets, seed=7, iterations=200)
    exp2 = monte_carlo_expectancy(nets, seed=7, iterations=200)
    assert exp1 == exp2
    assert lag1_autocorrelation(nets) is not None
    od = outlier_dependence(nets, top_removed=2)
    assert od.expectancy_all is not None
    curve = trade_removal_curve(nets, up_to=3)
    assert len(curve) == 4


def test_walk_forward_windows_are_out_of_sample() -> None:
    settings = _settings()
    ds = build_dataset(n_1h=200)
    report = walk_forward(
        ds, n_splits=3,
        backtest_config=BacktestConfig(min_operational_trades=5),
        indicator_config=small_indicator_config(),
        strategy_config=settings.strategy_config(),
        cost_config=settings.cost_config(),
        sizing_config=permissive_sizing_config(),
        risk_config=permissive_risk_config(),
        paper_config=settings.paper_config(),
        min_operational_trades=5,
    )
    assert report.windows
    for w in report.windows:
        assert w.oos.start >= w.in_sample.start  # OOS never precedes in-sample


def test_chronological_split_is_ordered() -> None:
    ds = build_dataset()
    parts = chronological_split(ds, train=0.6, validation=0.2, test=0.2)
    assert parts["train"].end <= parts["validation"].start
    assert parts["validation"].end <= parts["test"].start


def test_preregistration_rejects_posthoc_thresholds() -> None:
    ds = build_dataset()
    prereg = PreRegistration(
        dataset_hash=ds.content_hash, seed=1, hypotheses=("uptrend pullback",),
        thresholds={"min_profit_factor": 1.3}, splits={},
    )
    assert_thresholds_preregistered(prereg, {"min_profit_factor": 1.3})  # ok
    import pytest

    with pytest.raises(PreRegistrationError):
        assert_thresholds_preregistered(prereg, {"min_sharpe": 1.0})  # not pre-registered
    with pytest.raises(PreRegistrationError):
        assert_thresholds_preregistered(prereg, {"min_profit_factor": 1.5})  # retuned


def test_benchmark_is_context_only() -> None:
    settings = _settings()
    ds = build_dataset()
    bench = buy_and_hold(
        ds, Symbol.parse("BTC/USDT"), starting_equity=Decimal("10000"),
        cost_config=settings.cost_config(),
    )
    assert bench is not None
    assert "context" in bench.note.lower()
    assert bench.starting_equity == 10000.0
