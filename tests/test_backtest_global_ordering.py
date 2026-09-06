"""Global chronological ordering + same-timestamp correlation cap (plan §9.1)."""

from __future__ import annotations

from app.config import load_settings
from app.market_data.models import Symbol
from tests.fixtures.backtest_data import (
    build_dataset,
    run_fixture_backtest,
    tight_correlated_risk_config,
    trade_signatures,
)


def _settings():
    return load_settings(_env_file=None, environment="test")


def test_reversing_input_symbol_order_is_identical() -> None:
    settings = _settings()
    ds = build_dataset()
    forward = run_fixture_backtest(
        ds, settings, symbols=[Symbol.parse("BTC/USDT"), Symbol.parse("ETH/USDT")]
    )
    reverse = run_fixture_backtest(
        ds, settings, symbols=[Symbol.parse("ETH/USDT"), Symbol.parse("BTC/USDT")]
    )
    # Byte-identical results regardless of input symbol order (canonical rank).
    assert trade_signatures(forward) == trade_signatures(reverse)
    assert str(forward.ending_equity) == str(reverse.ending_equity)


def test_same_timestamp_correlated_cap_blocks_second_symbol() -> None:
    settings = _settings()
    ds = build_dataset()
    permissive = run_fixture_backtest(ds, settings)
    tight = run_fixture_backtest(ds, settings, risk_config=tight_correlated_risk_config())
    # The correlated cap deterministically blocks the second same-boundary entry.
    assert len(tight.trades) < len(permissive.trades)
    reasons = {e.detail for e in tight.events if e.kind.startswith("risk")}
    assert "exceeds_correlated" in reasons
    # Determinism of the capped run.
    tight2 = run_fixture_backtest(ds, settings, risk_config=tight_correlated_risk_config())
    assert trade_signatures(tight) == trade_signatures(tight2)


def test_shared_account_single_source_of_truth() -> None:
    # With both symbols trading against ONE shared account, total exposure at any
    # entry never exceeds equity (cash cannot go negative).
    settings = _settings()
    ds = build_dataset()
    result = run_fixture_backtest(ds, settings)
    assert all(p.cash >= 0 for p in result.equity_curve)
