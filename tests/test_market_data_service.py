"""Service contract: end-to-end, persist-vs-usability, incomplete exclusion, offline."""

from __future__ import annotations

from datetime import timedelta

from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.models import Symbol, Timeframe
from app.market_data.repository import CandleRepository
from app.market_data.service import MarketDataService
from tests.fixtures.market_data import BASE, h1, now_after, valid_h1_series

BTC = Symbol.parse("BTC/USDT")
H1 = Timeframe.H1


def _service(db, ohlcv):
    _engine, sf, _url = db
    adapter = FixtureExchangeAdapter(
        ohlcv={("BTC/USDT", "1h"): ohlcv}, symbols=[BTC], timeframes=[H1]
    )
    return adapter, MarketDataService(repository=CandleRepository(sf))


def test_end_to_end_usable_and_persisted(db) -> None:
    adapter, svc = _service(db, valid_h1_series(3))
    res = svc.get_candles(adapter, BTC, H1, now=now_after(3), persist=True)
    assert res.usable is True
    assert len(res.candles) == 3
    assert res.upsert is not None and res.upsert.inserted == 3


def test_valid_closed_candles_persist_despite_gap(db) -> None:
    adapter, svc = _service(db, [h1(0), h1(2)])  # gap at hour 1
    res = svc.get_candles(adapter, BTC, H1, now=now_after(3), persist=True)
    assert res.usable is False  # gapped series not usable
    assert len(res.candles) == 2
    assert res.upsert is not None and res.upsert.inserted == 2  # still persisted


def test_valid_closed_candles_persist_despite_stale(db) -> None:
    adapter, svc = _service(db, valid_h1_series(3))
    res = svc.get_candles(adapter, BTC, H1, now=now_after(100), persist=True)
    assert res.result.quality.stale is True
    assert res.usable is False
    assert res.upsert is not None and res.upsert.inserted == 3  # still persisted


def test_incomplete_not_returned_or_persisted(db) -> None:
    adapter, svc = _service(db, valid_h1_series(5))
    now = BASE + timedelta(hours=4, minutes=30)  # candle 4 incomplete
    res = svc.get_candles(adapter, BTC, H1, now=now, persist=True)
    assert len(res.candles) == 4
    assert res.result.quality.incomplete_count == 1
    assert res.upsert is not None and res.upsert.inserted == 4

    repo = CandleRepository(db[1])
    assert repo.latest_open_time("fixture", BTC, H1) == BASE + timedelta(hours=3)
