"""Market-data configuration validates against Symbol/Timeframe (source of truth)."""

from __future__ import annotations

import pytest

from app.config import load_settings
from app.exceptions import ConfigError


def test_market_defaults() -> None:
    s = load_settings(_env_file=None)
    assert s.market_symbols == ["BTC/USDT", "ETH/USDT"]
    assert s.market_timeframes == ["1h", "4h"]
    assert s.max_staleness_intervals == 1
    assert s.future_tolerance_seconds == 2
    assert s.ticker_staleness_seconds == 30


def test_invalid_symbol_rejected() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, market_symbols=["BTCUSDT"])


def test_invalid_timeframe_rejected() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, market_timeframes=["2h"])
