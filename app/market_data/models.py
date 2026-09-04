"""Canonical market-data models (Phase 1).

Two layers (v3 normalization boundary):

* ``RawCandle`` / ``RawTicker`` — UNTRUSTED DTOs produced by an adapter. Fields
  are permissive; malformed values become data-quality *issues* (never
  exceptions). The validation layer converts accepted rows into the strict
  canonical models below.
* ``Candle`` / ``Ticker`` — STRICT canonical models. Anything typed as one of
  these is guaranteed timezone-aware UTC with ``Decimal`` money fields, so
  downstream phases can rely on the invariants.

No float is ever accepted for money. UTC is canonical (Master Plan §18.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

# Permissive raw money type: adapters may hand us strings or Decimals (or None
# / non-finite Decimals for malformed data). Float is deliberately excluded.
RawMoney = Decimal | str | None


def to_money(value: Decimal | str | int) -> Decimal:
    """Convert an exact numeric input to ``Decimal``.

    Floats are rejected to avoid silent binary-float imprecision. Booleans are
    rejected because ``bool`` is an ``int`` subclass and would be surprising.
    """
    if isinstance(value, bool):
        raise TypeError("bool is not a valid money value")
    if isinstance(value, float):
        raise TypeError("float is not allowed for money; use str/int/Decimal")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (str, int)):
        return Decimal(value)
    raise TypeError(f"unsupported money type: {type(value)!r}")


class Timeframe(StrEnum):
    """Supported candle timeframes. This enum is the source of truth."""

    H1 = "1h"
    H4 = "4h"

    @property
    def seconds(self) -> int:
        return {Timeframe.H1: 3600, Timeframe.H4: 14400}[self]

    @property
    def delta(self) -> timedelta:
        return timedelta(seconds=self.seconds)


@dataclass(frozen=True)
class Symbol:
    """A canonical trading pair, e.g. ``BTC/USDT``."""

    base: str
    quote: str

    _PART_MIN = 2
    _PART_MAX = 15

    @classmethod
    def parse(cls, text: str) -> Symbol:
        if not isinstance(text, str) or text.count("/") != 1:
            raise ValueError(f"invalid symbol format: {text!r} (expected BASE/QUOTE)")
        base, quote = text.split("/")
        for part in (base, quote):
            bad_len = not (cls._PART_MIN <= len(part) <= cls._PART_MAX)
            if bad_len or not part.isalnum() or not part.isupper():
                raise ValueError(f"invalid symbol part: {part!r}")
        return cls(base=base, quote=quote)

    def __str__(self) -> str:
        return f"{self.base}/{self.quote}"


@dataclass(frozen=True)
class RawCandle:
    """Untrusted candle candidate from an adapter (pre-validation)."""

    source: str
    symbol: str
    timeframe: str
    open_time: datetime | None
    open: RawMoney
    high: RawMoney
    low: RawMoney
    close: RawMoney
    volume: RawMoney


@dataclass(frozen=True)
class Candle:
    """Strict canonical OHLCV candle (guaranteed tz-aware UTC + Decimal)."""

    source: str
    symbol: Symbol
    timeframe: Timeframe
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None or self.open_time.utcoffset() != timedelta(0):
            raise ValueError("Candle.open_time must be timezone-aware UTC")
        for name in ("open", "high", "low", "close", "volume"):
            if not isinstance(getattr(self, name), Decimal):
                raise TypeError(f"Candle.{name} must be Decimal")

    @property
    def close_time(self) -> datetime:
        return self.open_time + self.timeframe.delta

    def is_closed(self, now: datetime) -> bool:
        """A candle is closed once its whole interval is in the past."""
        return self.close_time <= now


@dataclass(frozen=True)
class RawTicker:
    """Untrusted ticker from an adapter (pre-validation)."""

    source: str
    symbol: str
    timestamp: datetime | None
    bid: RawMoney
    ask: RawMoney
    last: RawMoney


@dataclass(frozen=True)
class Ticker:
    """Strict canonical ticker (guaranteed tz-aware UTC + Decimal)."""

    source: str
    symbol: Symbol
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    last: Decimal

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() != timedelta(0):
            raise ValueError("Ticker.timestamp must be timezone-aware UTC")
        for name in ("bid", "ask", "last"):
            if not isinstance(getattr(self, name), Decimal):
                raise TypeError(f"Ticker.{name} must be Decimal")


def utc_epoch_aligned(dt: datetime, timeframe: Timeframe) -> bool:
    """Canonical Phase 1 alignment: open_time falls on a UTC epoch boundary.

    Deterministic and timezone-independent (anchored at the Unix epoch,
    1970-01-01T00:00:00Z). This is *the* Phase 1 contract; future exchange
    adapters must normalize their native boundaries to it or reject.
    """
    return int(dt.astimezone(UTC).timestamp()) % timeframe.seconds == 0
