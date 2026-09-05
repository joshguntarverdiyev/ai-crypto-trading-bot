"""Cost-model configuration and version tag (Phase 3 — source of truth).

All values are percentages expressed as decimal ratios on the same scale as
``ATR_pct`` (``0.001`` = 0.1%), consistent with the Phase 2 numeric policy.

The defaults are **illustrative, provisional, versioned placeholders** — NOT a
committed or real exchange fee and NOT calibrated (calibration is P7
backtesting). They are exchange-agnostic: an exchange-specific fee is resolved
into this config later, never hardcoded in business logic (Master Plan §0.2-4,
§14).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

COST_MODEL_VERSION = "cost-v1"


class CostScenario(StrEnum):
    """Cost realism tier (Master Plan §10). Conservative is the gate default."""

    OPTIMISTIC = "optimistic"
    BASE = "base"
    CONSERVATIVE = "conservative"


@dataclass(frozen=True)
class CostConfig:
    """Component percentages for the ``min_net_edge_pct`` model (Master Plan §4).

    Invariants: every value is a non-negative ratio; ``maker_fee_pct <=
    taker_fee_pct``; scenario multipliers are strictly increasing
    (``optimistic < base < conservative``) and positive.
    """

    taker_fee_pct: float = 0.001  # illustrative — per-side taker fee
    maker_fee_pct: float = 0.0008  # illustrative — per-side maker fee
    spread_fallback_pct: float = 0.0005  # conservative when no ticker available
    slippage_base_pct: float = 0.0005  # base execution friction
    slippage_opt_mult: float = 0.5
    slippage_base_mult: float = 1.0
    slippage_cons_mult: float = 2.0
    atr_vol_coefficient: float = 0.1  # volatility component = coef * ATR_pct (capped)
    atr_vol_cap_pct: float = 0.01  # cap; also the conservative value when ATR_pct unknown
    liquidity_buffer_pct: float = 0.0005  # conservative constant (no order book in P0–8)
    execution_uncertainty_pct: float = 0.0005
    model_uncertainty_pct: float = 0.0005
    safety_margin_pct: float = 0.0005

    def __post_init__(self) -> None:
        non_negative = (
            "taker_fee_pct",
            "maker_fee_pct",
            "spread_fallback_pct",
            "slippage_base_pct",
            "atr_vol_coefficient",
            "atr_vol_cap_pct",
            "liquidity_buffer_pct",
            "execution_uncertainty_pct",
            "model_uncertainty_pct",
            "safety_margin_pct",
        )
        for name in non_negative:
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must be >= 0")
        if self.maker_fee_pct > self.taker_fee_pct:
            raise ValueError("require maker_fee_pct <= taker_fee_pct")
        if not (0.0 < self.slippage_opt_mult < self.slippage_base_mult < self.slippage_cons_mult):
            raise ValueError(
                "require 0 < slippage_opt_mult < slippage_base_mult < slippage_cons_mult"
            )

    def scenario_multiplier(self, scenario: CostScenario) -> float:
        return {
            CostScenario.OPTIMISTIC: self.slippage_opt_mult,
            CostScenario.BASE: self.slippage_base_mult,
            CostScenario.CONSERVATIVE: self.slippage_cons_mult,
        }[scenario]

    @property
    def version_tag(self) -> str:
        return (
            f"{COST_MODEL_VERSION}|fee{self.taker_fee_pct}/{self.maker_fee_pct}"
            f"|spr{self.spread_fallback_pct}|slp{self.slippage_base_pct}"
            f"|mult{self.slippage_opt_mult}/{self.slippage_base_mult}/{self.slippage_cons_mult}"
            f"|atr{self.atr_vol_coefficient}c{self.atr_vol_cap_pct}"
            f"|liq{self.liquidity_buffer_pct}|exu{self.execution_uncertainty_pct}"
            f"|mdu{self.model_uncertainty_pct}|sm{self.safety_margin_pct}"
        )
