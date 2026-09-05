"""Indicator configuration and version tag (Phase 2 — source of truth)."""

from __future__ import annotations

from dataclasses import dataclass

INDICATOR_SET_VERSION = "ind-v1"


@dataclass(frozen=True)
class IndicatorConfig:
    """Baseline indicator periods. ``ema_short < ema_long`` is an invariant."""

    ema_short: int = 50
    ema_long: int = 200
    rsi_period: int = 14
    atr_period: int = 14

    def __post_init__(self) -> None:
        if not (0 < self.ema_short < self.ema_long):
            raise ValueError("require 0 < ema_short < ema_long")
        if self.rsi_period <= 0 or self.atr_period <= 0:
            raise ValueError("rsi_period and atr_period must be > 0")

    @property
    def min_history(self) -> int:
        """Candles needed for a fully-warm snapshot (all indicators available)."""
        return max(self.ema_long, self.rsi_period + 1, self.atr_period + 1)

    @property
    def version_tag(self) -> str:
        return (
            f"{INDICATOR_SET_VERSION}|ema{self.ema_short}/{self.ema_long}"
            f"|rsi{self.rsi_period}|atr{self.atr_period}"
        )
