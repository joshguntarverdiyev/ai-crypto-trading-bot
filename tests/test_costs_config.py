"""CostConfig invariants, version tag, and Settings.cost_config()/scenario."""

from __future__ import annotations

import pytest

from app.config import load_settings
from app.costs.config import COST_MODEL_VERSION, CostConfig, CostScenario
from app.exceptions import ConfigError


def test_defaults_are_valid_and_versioned() -> None:
    cfg = CostConfig()
    assert cfg.version_tag.startswith(COST_MODEL_VERSION)
    # maker is the cheaper (or equal) side; scenario multipliers strictly increase
    assert cfg.maker_fee_pct <= cfg.taker_fee_pct
    assert (
        cfg.scenario_multiplier(CostScenario.OPTIMISTIC)
        < cfg.scenario_multiplier(CostScenario.BASE)
        < cfg.scenario_multiplier(CostScenario.CONSERVATIVE)
    )


def test_rejects_negative_values() -> None:
    with pytest.raises(ValueError):
        CostConfig(taker_fee_pct=-0.001)
    with pytest.raises(ValueError):
        CostConfig(safety_margin_pct=-0.0001)


def test_rejects_maker_above_taker() -> None:
    with pytest.raises(ValueError):
        CostConfig(taker_fee_pct=0.001, maker_fee_pct=0.002)


def test_rejects_non_increasing_scenario_multipliers() -> None:
    with pytest.raises(ValueError):
        CostConfig(slippage_opt_mult=1.0, slippage_base_mult=1.0, slippage_cons_mult=2.0)
    with pytest.raises(ValueError):
        CostConfig(slippage_opt_mult=0.0, slippage_base_mult=1.0, slippage_cons_mult=2.0)


def test_settings_builds_cost_config_and_scenario() -> None:
    s = load_settings(_env_file=None)
    cfg = s.cost_config()
    assert isinstance(cfg, CostConfig)
    assert cfg.taker_fee_pct == 0.001
    assert s.default_cost_scenario() is CostScenario.CONSERVATIVE


def test_settings_rejects_bad_cost_params() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, cost_taker_fee_pct=0.001, cost_maker_fee_pct=0.01)
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, cost_scenario="aggressive")
