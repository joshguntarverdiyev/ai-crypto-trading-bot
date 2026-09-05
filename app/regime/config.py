"""Regime configuration and version tag (Phase 2).

Thresholds are configuration parameters — provisional, versioned baseline
defaults. They are NOT research-optimized in Phase 2; calibration is P4/
backtesting. Same decimal-ratio scale as ``ATR_pct = ATR/close`` (0.02 = 2%).
"""

from __future__ import annotations

from dataclasses import dataclass

REGIME_VERSION = "reg-v1"


@dataclass(frozen=True)
class RegimeConfig:
    trend_band: float = 0.002  # EMA separation neutral band (0.2%) — provisional
    vol_low_pct: float = 0.005  # 0.5% ATR% — provisional
    vol_high_pct: float = 0.02  # 2% ATR% — provisional

    def __post_init__(self) -> None:
        if self.trend_band <= 0:
            raise ValueError("trend_band must be > 0")
        if not (0 < self.vol_low_pct < self.vol_high_pct):
            raise ValueError("require 0 < vol_low_pct < vol_high_pct")

    @property
    def version_tag(self) -> str:
        return (
            f"{REGIME_VERSION}|tb{self.trend_band}"
            f"|vl{self.vol_low_pct}|vh{self.vol_high_pct}"
        )
