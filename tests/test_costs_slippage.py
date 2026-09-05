"""Slippage (scenario-scaled) and volatility (ATR_pct-driven) components."""

from __future__ import annotations

import pytest

from app.costs.config import CostConfig, CostScenario
from app.costs.slippage import slippage_pct, volatility_pct

CFG = CostConfig(
    slippage_base_pct=0.0005,
    slippage_opt_mult=0.5,
    slippage_base_mult=1.0,
    slippage_cons_mult=2.0,
    atr_vol_coefficient=0.1,
    atr_vol_cap_pct=0.01,
)


def test_slippage_monotonic_in_scenario() -> None:
    opt = slippage_pct(CFG, CostScenario.OPTIMISTIC)
    base = slippage_pct(CFG, CostScenario.BASE)
    cons = slippage_pct(CFG, CostScenario.CONSERVATIVE)
    assert opt < base < cons
    assert (opt, base, cons) == (0.00025, 0.0005, 0.001)


def test_volatility_monotonic_in_atr_and_capped() -> None:
    assert volatility_pct(CFG, 0.0) == 0.0
    assert volatility_pct(CFG, 0.02) == pytest.approx(0.002)  # 0.1 * 0.02
    assert volatility_pct(CFG, 0.05) == pytest.approx(0.005)
    # capped at atr_vol_cap_pct
    assert volatility_pct(CFG, 1.0) == 0.01
    lo, hi = volatility_pct(CFG, 0.01), volatility_pct(CFG, 0.03)
    assert lo < hi


def test_volatility_missing_atr_uses_conservative_cap() -> None:
    assert volatility_pct(CFG, None) == CFG.atr_vol_cap_pct


def test_volatility_clamps_negative_atr() -> None:
    assert volatility_pct(CFG, -0.5) == 0.0


def test_deterministic() -> None:
    assert slippage_pct(CFG, CostScenario.BASE) == slippage_pct(CFG, CostScenario.BASE)
    assert volatility_pct(CFG, 0.02) == volatility_pct(CFG, 0.02)
