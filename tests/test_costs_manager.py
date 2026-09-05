"""CostManager: min_net_edge composition, the net-edge gate, and fail-safe paths."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.costs.config import COST_MODEL_VERSION, CostConfig, CostScenario
from app.costs.manager import CostManager
from app.costs.models import CostReason, EdgeDecision
from app.market_data.models import Symbol, Ticker

BTC = Symbol.parse("BTC/USDT")
TS = datetime(2026, 1, 1, tzinfo=UTC)

# Clean round numbers so the expected min_net_edge is easy to reason about.
CFG = CostConfig(
    taker_fee_pct=0.001,
    maker_fee_pct=0.001,
    spread_fallback_pct=0.001,
    slippage_base_pct=0.001,
    slippage_opt_mult=0.5,
    slippage_base_mult=1.0,
    slippage_cons_mult=2.0,
    atr_vol_coefficient=0.1,
    atr_vol_cap_pct=0.01,
    liquidity_buffer_pct=0.001,
    execution_uncertainty_pct=0.001,
    model_uncertainty_pct=0.001,
    safety_margin_pct=0.001,
)
MGR = CostManager(CFG)

# Conservative, fallback spread, atr_pct=0.02 → components sum to 0.011.
EXPECTED_MIN_EDGE = 0.011


def _components_sum(breakdown) -> float:
    return math.fsum(
        (
            breakdown.entry_fee_pct,
            breakdown.exit_fee_pct,
            breakdown.spread_pct,
            breakdown.slippage_pct,
            breakdown.execution_uncertainty_pct,
            breakdown.model_uncertainty_pct,
            breakdown.safety_margin_pct,
            breakdown.volatility_pct,
            breakdown.liquidity_pct,
        )
    )


def test_min_net_edge_component_sum() -> None:
    b = MGR.min_net_edge(atr_pct=0.02, scenario=CostScenario.CONSERVATIVE)
    assert b.min_net_edge_pct == _components_sum(b)  # exact: same fsum
    assert b.min_net_edge_pct == pytest.approx(EXPECTED_MIN_EDGE)
    assert b.slippage_pct == 0.002  # base 0.001 * conservative 2.0
    assert b.volatility_pct == pytest.approx(0.002)  # 0.1 * 0.02
    assert b.cost_model_version == COST_MODEL_VERSION
    assert b.config_version.startswith(COST_MODEL_VERSION)


def test_pass_when_gross_exceeds_min_edge() -> None:
    a = MGR.assess_edge(expected_gross_move_pct=0.02, atr_pct=0.02)
    assert a.decision is EdgeDecision.PASS
    assert a.reason is CostReason.OK
    assert a.net_edge_pct == pytest.approx(0.02 - EXPECTED_MIN_EDGE)
    assert a.scenario is CostScenario.CONSERVATIVE  # gate default


def test_hold_when_gross_too_thin() -> None:
    a = MGR.assess_edge(expected_gross_move_pct=0.005, atr_pct=0.02)
    assert a.decision is EdgeDecision.HOLD
    assert a.reason is CostReason.BELOW_MIN_EDGE


def test_hold_when_gross_exactly_equals_min_edge() -> None:
    # Use the exact computed min edge so the boundary is truly net == 0.
    min_edge = MGR.min_net_edge(atr_pct=0.02).min_net_edge_pct
    a = MGR.assess_edge(expected_gross_move_pct=min_edge, atr_pct=0.02)
    assert a.decision is EdgeDecision.HOLD  # strict > required
    assert a.net_edge_pct == 0.0


def test_missing_spread_uses_conservative_fallback_flagged() -> None:
    a = MGR.assess_edge(expected_gross_move_pct=0.02, atr_pct=0.02, ticker=None)
    assert a.breakdown.spread_estimated is True
    assert a.breakdown.spread_pct == CFG.spread_fallback_pct
    assert CostReason.SPREAD_ESTIMATED in a.warnings


def test_live_ticker_spread_not_flagged() -> None:
    ticker = Ticker(
        source="fixture", symbol=BTC, timestamp=TS,
        bid=Decimal("99"), ask=Decimal("101"), last=Decimal("100"),
    )
    b = MGR.min_net_edge(atr_pct=0.02, ticker=ticker)
    assert b.spread_estimated is False
    assert b.spread_pct == 0.02


def test_missing_atr_uses_conservative_cap_flagged() -> None:
    a = MGR.assess_edge(expected_gross_move_pct=0.05, atr_pct=None)
    assert a.breakdown.feature_missing is True
    assert a.breakdown.volatility_pct == CFG.atr_vol_cap_pct
    assert CostReason.MISSING_FEATURE in a.warnings
    # Missing (None) is NOT non-finite: it must degrade conservatively and still
    # produce a real decision — never the hard-fail HOLD/NON_FINITE path.
    assert a.reason is not CostReason.NON_FINITE
    assert a.decision is EdgeDecision.PASS  # 0.05 gross clears the capped min edge
    assert a.net_edge_pct is not None


def test_non_finite_or_missing_gross_move_holds() -> None:
    for bad in (None, float("nan"), float("inf")):
        a = MGR.assess_edge(expected_gross_move_pct=bad, atr_pct=0.02)
        assert a.decision is EdgeDecision.HOLD
        assert a.reason is CostReason.NON_FINITE
        assert a.net_edge_pct is None
    missing = MGR.assess_edge(expected_gross_move_pct=None, atr_pct=0.02)
    assert missing.expected_gross_move_pct is None


def test_non_finite_atr_holds() -> None:
    a = MGR.assess_edge(expected_gross_move_pct=0.02, atr_pct=float("inf"))
    assert a.decision is EdgeDecision.HOLD
    assert a.reason is CostReason.NON_FINITE
    # non-finite ATR is treated as unavailable → conservative cap in the breakdown
    assert a.breakdown.volatility_pct == CFG.atr_vol_cap_pct


def test_scenario_monotonic_min_edge() -> None:
    opt = MGR.min_net_edge(atr_pct=0.02, scenario=CostScenario.OPTIMISTIC).min_net_edge_pct
    base = MGR.min_net_edge(atr_pct=0.02, scenario=CostScenario.BASE).min_net_edge_pct
    cons = MGR.min_net_edge(atr_pct=0.02, scenario=CostScenario.CONSERVATIVE).min_net_edge_pct
    assert opt < base < cons


def test_deterministic_reproducible() -> None:
    a1 = MGR.assess_edge(expected_gross_move_pct=0.02, atr_pct=0.02)
    a2 = MGR.assess_edge(expected_gross_move_pct=0.02, atr_pct=0.02)
    assert a1 == a2
