"""Slippage and volatility cost components (Phase 3).

Master Plan §9 forbids order-book depth in P0–8, so slippage is a conservative
parametric model — NOT depth-based. Per §4, slippage (execution friction, scaled
by the cost scenario) and the ATR_pct-driven volatility term are **separate**
components, so ATR is never double-counted.

Both functions are pure and deterministic. The regime *label* is never used —
only the raw ``ATR_pct`` feature (regime stays descriptive).
"""

from __future__ import annotations

from app.costs.config import CostConfig, CostScenario


def slippage_pct(config: CostConfig, scenario: CostScenario) -> float:
    """Execution-friction slippage, scaled by the cost scenario.

    Monotonic in scenario (optimistic < base < conservative).
    """
    return config.slippage_base_pct * config.scenario_multiplier(scenario)


def volatility_pct(config: CostConfig, atr_pct: float | None) -> float:
    """ATR_pct-driven volatility component, ``min(coef * ATR_pct, cap)``.

    Fail-safe: when ``atr_pct`` is unavailable, assume the cap (the conservative,
    highest value) rather than zero. Negative inputs are clamped to 0.
    """
    if atr_pct is None:
        return config.atr_vol_cap_pct
    return min(config.atr_vol_coefficient * max(atr_pct, 0.0), config.atr_vol_cap_pct)
