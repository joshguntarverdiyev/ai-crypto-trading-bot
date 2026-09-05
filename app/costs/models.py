"""Cost-model result types (Phase 3).

Descriptive, deterministic outputs of the cost side of the pipeline. The
edge gate implemented here is the cost half of Master Plan §4 only —
``expected_gross_move_pct - min_net_edge_pct > 0``. The ``reward:risk`` half
needs stop distance / target (strategy + sizing) and is deferred to P4.

All percentages are decimal ratios (``0.001`` = 0.1%). ``None`` is used only for
inputs that were genuinely unavailable; it never means "safe" (fail-safe:
Master Plan §0.1-3 / non-negotiable rule 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.costs.config import CostScenario


class EdgeDecision(StrEnum):
    PASS = "pass"
    HOLD = "hold"


class CostReason(StrEnum):
    OK = "ok"
    BELOW_MIN_EDGE = "below_min_edge"
    SPREAD_ESTIMATED = "spread_estimated"  # ticker unavailable → conservative fallback
    MISSING_FEATURE = "missing_feature"  # atr_pct unavailable → conservative buffer
    NON_FINITE = "non_finite"  # non-finite / missing input → HOLD


@dataclass(frozen=True)
class CostBreakdown:
    """The itemized ``min_net_edge_pct`` components (Master Plan §4)."""

    entry_fee_pct: float
    exit_fee_pct: float
    spread_pct: float
    slippage_pct: float
    execution_uncertainty_pct: float
    model_uncertainty_pct: float
    safety_margin_pct: float
    volatility_pct: float  # ATR_pct-driven component of §4 f(ATR_pct, ...)
    liquidity_pct: float  # conservative constant (no order book in P0–8)
    min_net_edge_pct: float  # exact sum of the components above
    scenario: CostScenario
    spread_estimated: bool
    feature_missing: bool  # atr_pct was unavailable → conservative buffer used
    cost_model_version: str
    config_version: str


@dataclass(frozen=True)
class EdgeAssessment:
    """Outcome of the cost-side net-edge gate for a candidate's expected move."""

    decision: EdgeDecision
    reason: CostReason
    expected_gross_move_pct: float | None  # None if the input was unavailable
    min_net_edge_pct: float
    net_edge_pct: float | None  # gross - min; None when gross was unavailable
    breakdown: CostBreakdown
    scenario: CostScenario
    warnings: tuple[CostReason, ...]
