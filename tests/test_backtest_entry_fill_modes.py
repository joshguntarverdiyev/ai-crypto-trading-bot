"""Entry-fill modes: next_open vs signal_close, and no i+1 H/L/C leak (plan §10)."""

from __future__ import annotations

from decimal import Decimal

from app.config import load_settings
from app.market_data.models import Symbol, Timeframe
from backtesting.config import BacktestConfig, EntryFillRule
from backtesting.dataset import dataset_from_raw
from tests.fixtures.backtest_data import build_raw, run_fixture_backtest


def _settings():
    return load_settings(_env_file=None, environment="test")


def _run(ds, settings, fill):
    return run_fixture_backtest(
        ds, settings,
        backtest_config=BacktestConfig(min_operational_trades=5, entry_fill_rule=fill),
    )


def test_next_open_and_signal_close_differ_with_open_gap() -> None:
    settings = _settings()
    # open_gap makes bar-i+1 open differ from bar-i close, so the modes diverge.
    ds = dataset_from_raw("gap", build_raw(open_gap=0.002))
    r_next = _run(ds, settings, EntryFillRule.NEXT_OPEN)
    r_sig = _run(ds, settings, EntryFillRule.SIGNAL_CLOSE)
    assert r_next.trades and r_sig.trades
    # Entry prices differ because the execution reference differs.
    assert r_next.trades[0].entry_price != r_sig.trades[0].entry_price


def _round_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    from decimal import ROUND_HALF_UP

    return (price / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick


def test_next_open_uses_the_entry_bar_open_price() -> None:
    """The next_open fill reference is the ENTRY BAR's open, never the prior close."""
    settings = _settings()
    ds = dataset_from_raw("gap", build_raw(open_gap=0.002))
    result = _run(ds, settings, EntryFillRule.NEXT_OPEN)
    assert result.trades

    cost = settings.cost_config()
    tick = settings.paper_config().tick_size
    # Adverse BUY factor applied by the (unmodified) PaperBroker.
    half_spread = Decimal(str(cost.spread_fallback_pct)) / 2
    slip = Decimal(str(cost.slippage_base_pct)) * Decimal(str(cost.slippage_cons_mult))
    factor = Decimal(1) + half_spread + slip

    trade = result.trades[0]
    candles = ds.candles(Symbol.parse(trade.symbol), Timeframe.H1)
    by_close = {c.close_time: c for c in candles}
    entry_bar = by_close[trade.entry_time]  # entry fills at the entry bar's close_time
    prev_bar = candles[candles.index(entry_bar) - 1]

    expected_from_open = _round_to_tick(entry_bar.open * factor, tick)
    expected_from_prev_close = _round_to_tick(prev_bar.close * factor, tick)

    assert trade.entry_price == expected_from_open
    assert trade.entry_price != expected_from_prev_close  # NOT the prior close
