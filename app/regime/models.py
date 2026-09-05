"""Regime models (Phase 2).

Descriptive classification only — NOT a trading signal. ``stale`` is
BUILD/SERIES-level (``RegimeResult.stale``), never per historical snapshot.
``source``/``symbol`` on a snapshot come from the 1h primary feature, never
inherited from a 4h input.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.market_data.models import Symbol


class TrendRegime(StrEnum):
    UP = "up"
    DOWN = "down"
    RANGING = "ranging"
    UNKNOWN = "unknown"


class VolatilityRegime(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RegimeSnapshot:
    open_time: datetime
    symbol: Symbol
    source: str
    trend: TrendRegime
    volatility: VolatilityRegime
    trend_4h: TrendRegime
    confirmed: bool
    governing_4h_open_time: datetime | None
    regime_version: str


@dataclass(frozen=True)
class RegimeResult:
    snapshots: list[RegimeSnapshot]
    stale: bool  # BUILD/SERIES-LEVEL: from the 1h/4h FeatureResult.stale
    config_version: str
    regime_version: str
