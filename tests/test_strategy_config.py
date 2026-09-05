"""StrategyConfig invariants, version tag, and Settings.strategy_config()."""

from __future__ import annotations

import pytest

from app.config import load_settings
from app.costs.config import CostScenario
from app.exceptions import ConfigError
from app.strategy.config import STRATEGY_VERSION, StrategyConfig


def test_defaults_are_valid_and_versioned() -> None:
    cfg = StrategyConfig()
    assert cfg.version_tag.startswith(STRATEGY_VERSION)
    assert cfg.cost_scenario is CostScenario.CONSERVATIVE
    assert cfg.target_atr_mult / cfg.stop_atr_mult >= cfg.rr_threshold


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rsi_pullback_level": 0.0},
        {"rsi_pullback_level": 100.0},
        {"stop_atr_mult": 0.0},
        {"target_atr_mult": -1.0},
        {"rr_threshold": 0.5},
    ],
)
def test_rejects_bad_params(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        StrategyConfig(**kwargs)


def test_settings_builds_strategy_config() -> None:
    s = load_settings(_env_file=None)
    cfg = s.strategy_config()
    assert isinstance(cfg, StrategyConfig)
    assert cfg.rsi_pullback_level == 40.0
    # cost scenario flows from the shared cost_scenario setting
    assert cfg.cost_scenario is CostScenario.CONSERVATIVE


def test_settings_rejects_bad_strategy_params() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, strategy_rr_threshold=0.5)
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, strategy_rsi_pullback_level=150.0)
