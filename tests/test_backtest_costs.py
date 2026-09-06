"""Cost handling: fees counted once, no P3-buffer double count, scenario sweep (§12)."""

from __future__ import annotations

from decimal import Decimal

from app.config import load_settings
from backtesting.robustness import cost_scenario_sweep
from tests.fixtures.backtest_data import (
    build_dataset,
    permissive_risk_config,
    permissive_sizing_config,
    run_fixture_backtest,
    small_indicator_config,
)


def _settings():
    return load_settings(_env_file=None, environment="test")


def test_net_pnl_is_gross_minus_fees_only_no_double_count() -> None:
    settings = _settings()
    ds = build_dataset()
    result = run_fixture_backtest(ds, settings)
    assert result.trades
    for t in result.trades:
        # net == gross - entry_fee - exit_fee EXACTLY. No P3 min_net_edge buffer is
        # ever re-subtracted from realized PnL (plan §12).
        assert t.net_pnl == t.gross_pnl - t.entry_fee - t.exit_fee


def test_entry_fee_is_taker_on_executed_notional() -> None:
    settings = _settings()
    taker = Decimal(str(settings.cost_config().taker_fee_pct))
    ds = build_dataset()
    result = run_fixture_backtest(ds, settings)
    for t in result.trades:
        expected = (t.quantity * t.entry_price * taker).quantize(Decimal("0.00000001"))
        assert t.entry_fee == expected


def test_conservative_costs_are_not_better_than_optimistic() -> None:
    settings = _settings()
    from backtesting.config import BacktestConfig

    ds = build_dataset()
    sweep = cost_scenario_sweep(
        ds,
        backtest_config=BacktestConfig(min_operational_trades=5),
        indicator_config=small_indicator_config(),
        strategy_config=settings.strategy_config(),
        cost_config=settings.cost_config(),
        sizing_config=permissive_sizing_config(),
        risk_config=permissive_risk_config(),
        paper_config=settings.paper_config(),
        min_operational_trades=5,
    )
    opt = sweep["optimistic"].net_pnl
    cons = sweep["conservative"].net_pnl
    # Higher assumed costs never improve net PnL (a strategy good ONLY under
    # optimistic is not a success, §10).
    assert cons <= opt
