"""Market regime classification (Phase 2).

Deterministic, descriptive trend/volatility classification derived from Phase 2
features (1h primary, causal 4h confirmation with source+symbol isolation). Not
a trading signal. No strategy, sizing, risk, or execution.
"""

from __future__ import annotations

from app.regime.alignment import governing_4h
from app.regime.classifier import RegimeClassifier
from app.regime.config import REGIME_VERSION, RegimeConfig
from app.regime.models import (
    RegimeResult,
    RegimeSnapshot,
    TrendRegime,
    VolatilityRegime,
)

__all__ = [
    "RegimeConfig",
    "REGIME_VERSION",
    "RegimeClassifier",
    "RegimeSnapshot",
    "RegimeResult",
    "TrendRegime",
    "VolatilityRegime",
    "governing_4h",
]
