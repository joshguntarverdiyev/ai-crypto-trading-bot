"""No look-ahead / no future leakage (Phase 7, plan §10.6)."""

from __future__ import annotations

from app.config import load_settings
from tests.fixtures.backtest_data import build_dataset, run_fixture_backtest, trade_signatures


def _settings():
    return load_settings(_env_file=None, environment="test")


def test_appending_future_candles_does_not_change_past_trades() -> None:
    settings = _settings()
    short = build_dataset(name="short", n_1h=120)
    long = build_dataset(name="long", n_1h=160)  # identical first-120 prefix
    r_short = run_fixture_backtest(short, settings)
    r_long = run_fixture_backtest(long, settings)

    cut = max(c.close_time for c in short.candles(  # last decision boundary of short
        _sym(r_short), _tf()))
    long_pairs = zip(trade_signatures(r_long), r_long.trades, strict=True)
    short_pairs = zip(trade_signatures(r_short), r_short.trades, strict=True)
    long_prefix = [s for s, t in long_pairs if t.exit_time <= cut]
    short_all = [s for s, t in short_pairs if t.exit_time <= cut]
    # Every trade that completed within the shared prefix is byte-identical.
    assert short_all == long_prefix
    assert len(short_all) > 0


def _sym(result):
    from app.market_data.models import Symbol

    return Symbol.parse(result.manifest.symbols[0])


def _tf():
    from app.market_data.models import Timeframe

    return Timeframe.H1


def test_truncation_preserves_prefix_equity_path() -> None:
    settings = _settings()
    short = build_dataset(name="short", n_1h=120)
    long = build_dataset(name="long", n_1h=160)
    r_short = run_fixture_backtest(short, settings)
    r_long = run_fixture_backtest(long, settings)
    cut = r_short.equity_curve[-1].time
    long_prefix = [(p.time, str(p.equity)) for p in r_long.equity_curve if p.time <= cut]
    short_path = [(p.time, str(p.equity)) for p in r_short.equity_curve if p.time <= cut]
    assert short_path == long_prefix
