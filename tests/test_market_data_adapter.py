"""Adapter contract: support checks, empty, since (inclusive), limit, source id."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.exceptions import UnsupportedMarketError
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.models import Symbol, Timeframe
from tests.fixtures.market_data import BASE, valid_h1_series

BTC = Symbol.parse("BTC/USDT")
XRP = Symbol.parse("XRP/USDT")
H1 = Timeframe.H1


def _adapter() -> FixtureExchangeAdapter:
    return FixtureExchangeAdapter(
        ohlcv={("BTC/USDT", "1h"): valid_h1_series(5)},
        symbols=[BTC],
        timeframes=[H1],
    )


def test_unsupported_symbol_raises() -> None:
    with pytest.raises(UnsupportedMarketError):
        _adapter().fetch_ohlcv(XRP, H1)


def test_unsupported_timeframe_raises() -> None:
    with pytest.raises(UnsupportedMarketError):
        _adapter().fetch_ohlcv(BTC, Timeframe.H4)


def test_empty_response_is_empty_list() -> None:
    adapter = FixtureExchangeAdapter(symbols=[BTC], timeframes=[H1])
    assert adapter.fetch_ohlcv(BTC, H1) == []


def test_since_is_inclusive_and_limit_applies() -> None:
    adapter = _adapter()
    since = BASE + timedelta(hours=2)
    got = adapter.fetch_ohlcv(BTC, H1, since=since)
    assert [c.open_time for c in got] == [BASE + timedelta(hours=i) for i in (2, 3, 4)]

    limited = adapter.fetch_ohlcv(BTC, H1, limit=2)
    assert len(limited) == 2


def test_source_identity() -> None:
    adapter = FixtureExchangeAdapter(
        source_id="fixture",
        ohlcv={("BTC/USDT", "1h"): valid_h1_series(2)},
        symbols=[BTC],
        timeframes=[H1],
    )
    got = adapter.fetch_ohlcv(BTC, H1)
    assert all(c.source == adapter.id for c in got)
