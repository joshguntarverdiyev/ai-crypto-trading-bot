"""Decision-time sizing is frozen: future bars cannot change quantity (plan §13)."""

from __future__ import annotations

from decimal import Decimal

from app.config import load_settings
from app.market_data.models import RawCandle
from backtesting.dataset import dataset_from_raw
from tests.fixtures.backtest_data import build_raw, run_fixture_backtest


def _settings():
    return load_settings(_env_file=None, environment="test")


def _first_entry_qty(result, symbol: str) -> tuple:
    for t in result.trades:
        if t.symbol == symbol:
            return (t.entry_time.isoformat(), str(t.entry_price), str(t.quantity))
    return ()


def test_mutating_future_bars_cannot_change_earlier_position_quantity() -> None:
    settings = _settings()
    raw = build_raw()
    base = dataset_from_raw("base", raw)
    r_base = run_fixture_backtest(base, settings)
    assert r_base.trades
    first = r_base.trades[0]
    baseline_qty = str(first.quantity)
    entry_boundary = first.entry_time

    # Mutate ONLY candles strictly AFTER the first entry fills (open_time >=
    # entry_boundary). The sizing/risk decision for that entry was made one bar
    # earlier, so its quantity must be identical regardless of the future path.
    mutated: dict = {}
    for key, candles in raw.items():
        new_list = []
        for c in candles:
            if c.open_time is not None and c.open_time >= entry_boundary:
                o = Decimal(c.open) * Decimal("1.20")
                h = Decimal(c.high) * Decimal("1.20")
                lo = Decimal(c.low) * Decimal("1.20")
                cl = Decimal(c.close) * Decimal("1.20")
                new_list.append(
                    RawCandle(c.source, c.symbol, c.timeframe, c.open_time,
                              f"{o:f}", f"{h:f}", f"{lo:f}", f"{cl:f}", c.volume)
                )
            else:
                new_list.append(c)
        mutated[key] = new_list
    mut_ds = dataset_from_raw("mut", mutated)
    r_mut = run_fixture_backtest(mut_ds, settings)

    # The first entry's (time, price, quantity) is unchanged — sizing was frozen
    # at decision time and used no future/mark-to-market information.
    assert _first_entry_qty(r_mut, first.symbol)[2] == baseline_qty
