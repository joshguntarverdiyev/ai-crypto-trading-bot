"""Market-data foundation (Phase 1).

Exchange-agnostic interfaces + canonical models + deterministic validation +
candle persistence + ``MarketDataService`` (the single consumption point for
later phases). No indicators, strategy, trading, exchange/network code, or AI.
"""

from __future__ import annotations

from app.market_data.adapter import ExchangeAdapter
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.models import (
    Candle,
    RawCandle,
    RawTicker,
    Symbol,
    Ticker,
    Timeframe,
    to_money,
    utc_epoch_aligned,
)
from app.market_data.repository import CandleRepository, UpsertResult
from app.market_data.service import MarketDataResult, MarketDataService
from app.market_data.validation import (
    DataQuality,
    IssueCode,
    SeriesUsability,
    Severity,
    ValidationIssue,
    ValidationResult,
    validate_candles,
    validate_ticker,
)

__all__ = [
    "ExchangeAdapter",
    "FixtureExchangeAdapter",
    "Symbol",
    "Timeframe",
    "Candle",
    "Ticker",
    "RawCandle",
    "RawTicker",
    "to_money",
    "utc_epoch_aligned",
    "CandleRepository",
    "UpsertResult",
    "MarketDataService",
    "MarketDataResult",
    "validate_candles",
    "validate_ticker",
    "ValidationResult",
    "ValidationIssue",
    "DataQuality",
    "IssueCode",
    "Severity",
    "SeriesUsability",
]
