"""Strategy configuration and version tag (Phase 4 — source of truth).

The baseline hypothesis (a *candidate* baseline, NOT the final strategy, Master
Plan §5): in an established up-trend (1h EMA50 > EMA200, confirmed by the
governing 4h EMA50 > EMA200), an RSI pullback offers a long entry whose
ATR-based target clears costs with acceptable reward:risk.

**Contract clarification 1 (provisional model assumption, not a prediction):**
``stop_atr_mult`` / ``target_atr_mult`` / ``rr_threshold`` / ``rsi_pullback_level``
are provisional, versioned defaults. The ATR-based target is a *model assumption*
used to size the reward:risk and cost gates — it is NOT a claim that the target
will be reached and carries NO predictive-edge claim. P4 does not calibrate these
values; empirical validation and calibration are owned by P7.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.costs.config import CostScenario

STRATEGY_VERSION = "strat-v1"


@dataclass(frozen=True)
class StrategyConfig:
    """Provisional baseline parameters (long-only, §3). Not calibrated (P7)."""

    rsi_pullback_level: float = 40.0  # RSI at/below this = pullback within the trend
    stop_atr_mult: float = 1.5  # stop = entry - stop_atr_mult * ATR
    target_atr_mult: float = 3.0  # target = entry + target_atr_mult * ATR
    rr_threshold: float = 2.0  # required reward:risk (target_mult / stop_mult)
    require_4h_confirmation: bool = True
    cost_scenario: CostScenario = CostScenario.CONSERVATIVE  # gate default

    def __post_init__(self) -> None:
        if not (0.0 < self.rsi_pullback_level < 100.0):
            raise ValueError("require 0 < rsi_pullback_level < 100")
        if self.stop_atr_mult <= 0.0 or self.target_atr_mult <= 0.0:
            raise ValueError("stop_atr_mult and target_atr_mult must be > 0")
        if self.rr_threshold < 1.0:
            raise ValueError("rr_threshold must be >= 1")

    @property
    def version_tag(self) -> str:
        return (
            f"{STRATEGY_VERSION}|rsi{self.rsi_pullback_level}"
            f"|stop{self.stop_atr_mult}|tgt{self.target_atr_mult}"
            f"|rr{self.rr_threshold}|c4h{int(self.require_4h_confirmation)}"
            f"|sc{self.cost_scenario.value}"
        )
