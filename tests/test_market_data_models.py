"""Canonical model contracts: Symbol, Timeframe, money, Candle, Ticker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.market_data.models import (
    Candle,
    Symbol,
    Ticker,
    Timeframe,
    to_money,
    utc_epoch_aligned,
)


def test_symbol_parse_and_str() -> None:
    s = Symbol.parse("BTC/USDT")
    assert (s.base, s.quote) == ("BTC", "USDT")
    assert str(s) == "BTC/USDT"


@pytest.mark.parametrize("bad", ["BTCUSDT", "btc/usdt", "BTC/", "/USDT", "BTC/USDT/X", "B/USDT"])
def test_symbol_parse_rejects_bad(bad: str) -> None:
    with pytest.raises(ValueError):
        Symbol.parse(bad)


def test_timeframe_seconds_and_delta() -> None:
    assert Timeframe.H1.seconds == 3600
    assert Timeframe.H4.seconds == 14400
    assert Timeframe.H4.delta == timedelta(hours=4)


def test_to_money_rejects_float_and_bool() -> None:
    with pytest.raises(TypeError):
        to_money(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        to_money(True)  # type: ignore[arg-type]
    assert to_money("1.50") == Decimal("1.50")
    assert to_money(3) == Decimal(3)
    assert to_money(Decimal("2.5")) == Decimal("2.5")


def test_candle_rejects_naive_open_time() -> None:
    with pytest.raises(ValueError):
        Candle(
            source="fixture",
            symbol=Symbol.parse("BTC/USDT"),
            timeframe=Timeframe.H1,
            open_time=datetime(2026, 1, 1, 0, 0, 0),  # naive
            open=Decimal(1),
            high=Decimal(1),
            low=Decimal(1),
            close=Decimal(1),
            volume=Decimal(1),
        )


def test_candle_close_time_and_is_closed() -> None:
    ot = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    c = Candle(
        source="fixture",
        symbol=Symbol.parse("BTC/USDT"),
        timeframe=Timeframe.H1,
        open_time=ot,
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(10),
    )
    assert c.close_time == ot + timedelta(hours=1)
    assert c.is_closed(ot + timedelta(hours=1)) is True
    assert c.is_closed(ot + timedelta(minutes=59)) is False


def test_ticker_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        Ticker(
            source="fixture",
            symbol=Symbol.parse("BTC/USDT"),
            timestamp=datetime(2026, 1, 1),  # naive
            bid=Decimal(1),
            ask=Decimal(1),
            last=Decimal(1),
        )


def test_utc_epoch_alignment() -> None:
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert utc_epoch_aligned(base, Timeframe.H1) is True
    assert utc_epoch_aligned(base, Timeframe.H4) is True
    assert utc_epoch_aligned(base + timedelta(hours=1), Timeframe.H1) is True
    assert utc_epoch_aligned(base + timedelta(hours=1), Timeframe.H4) is False
    assert utc_epoch_aligned(base + timedelta(minutes=30), Timeframe.H1) is False
    # timezone-independent: same instant expressed in +02:00 is still aligned
    plus2 = base.astimezone(timezone(timedelta(hours=2)))
    assert utc_epoch_aligned(plus2, Timeframe.H1) is True
