"""Technical indicators / features (Phase 2).

Deterministic, causal, pure-Python indicators (EMA50/EMA200, RSI14, ATR14,
ATR%) computed from Phase 1 candle series via ``FeatureBuilder``. No strategy,
signals, trading, exchange/network, or AI.
"""

from __future__ import annotations

from app.indicators.config import INDICATOR_SET_VERSION, IndicatorConfig
from app.indicators.features import FeatureBuilder
from app.indicators.functions import atr_wilder, ema, rsi_wilder
from app.indicators.models import ComputeReason, FeatureResult, FeatureSnapshot

__all__ = [
    "IndicatorConfig",
    "INDICATOR_SET_VERSION",
    "FeatureBuilder",
    "FeatureSnapshot",
    "FeatureResult",
    "ComputeReason",
    "ema",
    "rsi_wilder",
    "atr_wilder",
]
