"""Stop/target/gap semantics through the backtest path (plan §16)."""

from __future__ import annotations

from app.config import load_settings
from tests.fixtures.backtest_data import (
    build_crash_dataset,
    build_dataset,
    run_fixture_backtest,
)


def _settings():
    return load_settings(_env_file=None, environment="test")


def test_all_exits_are_stop_or_target() -> None:
    settings = _settings()
    result = run_fixture_backtest(build_dataset(), settings)
    assert result.trades
    assert all(t.exit_reason in {"stop", "target"} for t in result.trades)


def test_uptrend_produces_target_exits() -> None:
    settings = _settings()
    result = run_fixture_backtest(build_dataset(), settings)
    assert any(t.exit_reason == "target" for t in result.trades)


def test_crash_produces_stop_exits_with_losses() -> None:
    settings = _settings()
    result = run_fixture_backtest(build_crash_dataset(), settings)
    stops = [t for t in result.trades if t.exit_reason == "stop"]
    assert stops, "a post-entry crash must trigger at least one stop-loss exit"
    # A stop exit is a loss (bot-managed stop; adverse fill can only worsen it).
    assert all(t.net_pnl < 0 for t in stops)
