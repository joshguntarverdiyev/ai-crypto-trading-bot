"""MarketDataService — the single consumption point for later phases (Phase 1).

Orchestrates: fetch (adapter) → validate/normalize → classify usability →
optionally persist eligible (valid, closed) candles → return a structured
result. Data-quality problems are returned in the result; only
infrastructure/programming problems raise.

Persistence eligibility != usability: a structurally-valid closed candle is
persist-eligible even if the overall series is gapped/stale; ``result.usable``
still reflects the series usability contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.market_data.adapter import ExchangeAdapter
from app.market_data.models import Candle, Symbol, Timeframe
from app.market_data.repository import CandleRepository, UpsertResult
from app.market_data.validation import ValidationResult, validate_candles


@dataclass(frozen=True)
class MarketDataResult:
    candles: list[Candle]
    result: ValidationResult
    upsert: UpsertResult | None = None

    @property
    def usable(self) -> bool:
        return self.result.usable


class MarketDataService:
    def __init__(self, repository: CandleRepository | None = None) -> None:
        self._repository = repository

    def get_candles(
        self,
        adapter: ExchangeAdapter,
        symbol: Symbol,
        timeframe: Timeframe,
        *,
        now: datetime,
        since: datetime | None = None,
        limit: int | None = None,
        persist: bool = False,
        max_staleness_intervals: int = 1,
        future_tolerance_seconds: int = 2,
    ) -> MarketDataResult:
        # May raise UnsupportedMarketError / AdapterError (infra), never for data quality.
        raw = adapter.fetch_ohlcv(symbol, timeframe, since, limit)

        candles, result = validate_candles(
            raw,
            symbol=symbol,
            timeframe=timeframe,
            now=now,
            max_staleness_intervals=max_staleness_intervals,
            future_tolerance_seconds=future_tolerance_seconds,
        )

        upsert: UpsertResult | None = None
        if persist and candles:
            if self._repository is None:
                raise ValueError("persist=True requires a repository")
            # Gaps/stale do NOT block persistence of valid closed candles.
            upsert = self._repository.upsert(candles)

        return MarketDataResult(candles=candles, result=result, upsert=upsert)
