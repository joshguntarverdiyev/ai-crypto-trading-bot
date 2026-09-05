"""Deterministic market-data fixtures (offline).

Programmatic builders (CSV cannot represent naive-vs-aware timestamps, Decimal
NaN/Infinity, etc.). ``BASE`` is aligned to both 1h and 4h UTC epoch boundaries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.market_data.models import RawCandle, RawTicker, Symbol, Timeframe
from app.market_data.service import MarketDataResult
from app.market_data.validation import validate_candles

BASE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)  # multiple of 3600 and 14400


def _d(x: object) -> Decimal | str | None:
    if x is None or isinstance(x, (Decimal, str)):
        return x
    raise TypeError("fixture money must be Decimal|str|None")


def raw_candle(
    open_time: datetime | None,
    *,
    source: str = "fixture",
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    o: object = "100",
    h: object = "110",
    lo: object = "90",
    c: object = "105",
    v: object = "10",
) -> RawCandle:
    return RawCandle(source, symbol, timeframe, open_time, _d(o), _d(h), _d(lo), _d(c), _d(v))


def h1(n: int, *, timeframe: str = "1h", **kw: object) -> RawCandle:
    """A 1h candle at BASE + n hours (epoch-aligned)."""
    return raw_candle(  # type: ignore[arg-type]
        BASE + timedelta(hours=n), timeframe=timeframe, **kw
    )


def valid_h1_series(n: int, **kw: object) -> list[RawCandle]:
    return [h1(i, **kw) for i in range(n)]


def now_after(n_hours: int) -> datetime:
    """A ``now`` at BASE + n hours (so candles 0..n-1 are all closed)."""
    return BASE + timedelta(hours=n_hours)


def market_result(
    raw: list[RawCandle],
    *,
    now: datetime,
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    max_staleness_intervals: int = 1,
) -> MarketDataResult:
    """Wrap raw candles into a Phase 1 MarketDataResult (offline, deterministic)."""
    sym = Symbol.parse(symbol)
    tf = Timeframe(timeframe)
    candles, result = validate_candles(
        raw, symbol=sym, timeframe=tf, now=now, max_staleness_intervals=max_staleness_intervals
    )
    return MarketDataResult(candles=candles, result=result)


def raw_ticker(
    *,
    source: str = "fixture",
    symbol: str = "BTC/USDT",
    timestamp: datetime | None = BASE,
    bid: object = "100",
    ask: object = "101",
    last: object = "100.5",
) -> RawTicker:
    return RawTicker(source, symbol, timestamp, _d(bid), _d(ask), _d(last))
