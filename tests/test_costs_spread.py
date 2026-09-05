"""Spread estimation from a Phase 1 Ticker, with conservative fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.costs.config import CostConfig
from app.costs.spread import resolve_spread_pct, spread_pct_from_ticker
from app.market_data.models import Symbol, Ticker

BTC = Symbol.parse("BTC/USDT")
TS = datetime(2026, 1, 1, tzinfo=UTC)
CFG = CostConfig(spread_fallback_pct=0.0005)


def _ticker(bid: str, ask: str, last: str = "100") -> Ticker:
    return Ticker(
        source="fixture",
        symbol=BTC,
        timestamp=TS,
        bid=Decimal(bid),
        ask=Decimal(ask),
        last=Decimal(last),
    )


def test_spread_from_valid_ticker() -> None:
    # bid=99, ask=101 -> mid=100 -> spread=2/100=0.02
    assert spread_pct_from_ticker(_ticker("99", "101")) == 0.02


def test_spread_none_when_crossed_or_zero_mid() -> None:
    assert spread_pct_from_ticker(_ticker("101", "99")) is None  # ask < bid
    assert spread_pct_from_ticker(_ticker("0", "0")) is None  # mid == 0


def test_resolve_uses_live_when_valid() -> None:
    value, estimated = resolve_spread_pct(CFG, _ticker("99", "101"))
    assert value == 0.02
    assert estimated is False


def test_resolve_falls_back_when_missing_or_invalid() -> None:
    value, estimated = resolve_spread_pct(CFG, None)
    assert (value, estimated) == (0.0005, True)
    value, estimated = resolve_spread_pct(CFG, _ticker("101", "99"))
    assert (value, estimated) == (0.0005, True)  # invalid ticker -> conservative fallback
