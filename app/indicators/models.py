"""Feature models (Phase 2).

``stale`` is SERIES/BUILD-LEVEL only (``FeatureResult.stale``, from Phase 1
``result.quality.stale``). It is deliberately NOT on ``FeatureSnapshot`` — a
historical candle is not "stale"; ``warm`` (candle-level) is the per-snapshot
readiness flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.market_data.models import Symbol, Timeframe


class ComputeReason(StrEnum):
    OK = "ok"
    INVALID = "invalid"
    GAP = "gap"
    EMPTY = "empty"
    NON_FINITE = "non_finite"


@dataclass(frozen=True)
class FeatureSnapshot:
    source: str
    symbol: Symbol
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    close: float
    ema_short: float | None
    ema_long: float | None
    rsi: float | None
    atr: float | None
    atr_pct: float | None
    warm: bool
    indicator_set_version: str


@dataclass(frozen=True)
class FeatureResult:
    snapshots: list[FeatureSnapshot]
    computed: bool
    reason: ComputeReason
    stale: bool  # SERIES/BUILD-LEVEL (Phase 1 result.quality.stale)
    config_version: str
