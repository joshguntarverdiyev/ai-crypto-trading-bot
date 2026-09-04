"""Repository: idempotency, conflict detection, source isolation, exact Decimal."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.market_data.models import Candle, Symbol, Timeframe
from app.market_data.repository import CandleRepository
from app.market_data.validation import validate_candles
from app.models import SystemEvent
from tests.fixtures.market_data import BASE, valid_h1_series

BTC = Symbol.parse("BTC/USDT")
H1 = Timeframe.H1


def _candles(n: int, **kw: object) -> list[Candle]:
    raw = valid_h1_series(n, **kw)
    candles, _ = validate_candles(raw, symbol=BTC, timeframe=H1, now=BASE + timedelta(hours=n))
    return candles


def test_upsert_is_idempotent(db) -> None:
    _engine, sf, _url = db
    repo = CandleRepository(sf)
    candles = _candles(3)

    r1 = repo.upsert(candles)
    assert (r1.inserted, r1.unchanged, r1.conflicts) == (3, 0, 0)

    r2 = repo.upsert(candles)  # same values again
    assert (r2.inserted, r2.unchanged, r2.conflicts) == (0, 3, 0)


def test_conflict_never_overwrites_and_records_event(db) -> None:
    _engine, sf, _url = db
    repo = CandleRepository(sf)
    original = _candles(1)
    repo.upsert(original)

    conflicting = [replace(original[0], close=Decimal("999"))]
    r = repo.upsert(conflicting)
    assert (r.inserted, r.unchanged, r.conflicts) == (0, 0, 1)

    # existing row NOT overwritten
    stored = repo.get("fixture", BTC, H1)
    assert stored[0].close == Decimal("105")

    # a conflict SystemEvent was written
    with sf() as s:
        events = s.scalars(
            select(SystemEvent).where(SystemEvent.component == "market_data.repository")
        ).all()
    assert len(events) == 1


def test_source_isolation(db) -> None:
    _engine, sf, _url = db
    repo = CandleRepository(sf)
    a = _candles(1, source="fixture")
    b = _candles(1, source="other")  # same symbol/tf/open_time, different source
    repo.upsert(a)
    repo.upsert(b)

    assert len(repo.get("fixture", BTC, H1)) == 1
    assert len(repo.get("other", BTC, H1)) == 1


def test_get_range_is_half_open_and_ordered(db) -> None:
    _engine, sf, _url = db
    repo = CandleRepository(sf)
    repo.upsert(_candles(5))
    start = BASE + timedelta(hours=1)
    end = BASE + timedelta(hours=4)
    got = repo.get("fixture", BTC, H1, start=start, end=end)
    assert [c.open_time for c in got] == [BASE + timedelta(hours=i) for i in (1, 2, 3)]


def test_latest_open_time(db) -> None:
    _engine, sf, _url = db
    repo = CandleRepository(sf)
    assert repo.latest_open_time("fixture", BTC, H1) is None
    repo.upsert(_candles(3))
    assert repo.latest_open_time("fixture", BTC, H1) == BASE + timedelta(hours=2)


def test_decimal_round_trip_is_exact(db) -> None:
    _engine, sf, _url = db
    repo = CandleRepository(sf)
    precise = replace(
        _candles(1)[0],
        open=Decimal("100.123456789012345678"),
        volume=Decimal("0.000000000000000001"),
    )
    repo.upsert([precise])
    got = repo.get("fixture", BTC, H1)[0]
    assert got.open == Decimal("100.123456789012345678")
    assert got.volume == Decimal("0.000000000000000001")
