"""SizingConfig invariants, version tag, and Settings.sizing_config()."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import load_settings
from app.exceptions import ConfigError
from app.sizing.config import SIZING_VERSION, SizingConfig


def test_defaults_are_valid_and_versioned() -> None:
    cfg = SizingConfig()
    assert cfg.version_tag.startswith(SIZING_VERSION)
    assert cfg.correlation_group_for("BTC") == frozenset({"BTC", "ETH"})
    assert cfg.correlation_group_for("LTC") == frozenset({"LTC"})  # ungrouped singleton


@pytest.mark.parametrize(
    "kwargs",
    [
        {"risk_per_trade_pct": 0.0},
        {"risk_per_trade_pct": 1.0},
        {"max_single_asset_exposure_pct": 0.0},
        {"max_total_exposure_pct": 1.5},
        {"max_simultaneous_positions": 0},
        {"min_notional": Decimal("0")},
        {"step_size": Decimal("-1")},
        {"tick_size": Decimal("0")},
        {"liquidity_cap_quote": Decimal("0")},
    ],
)
def test_rejects_bad_params(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        SizingConfig(**kwargs)


def test_settings_builds_sizing_config() -> None:
    s = load_settings(_env_file=None)
    cfg = s.sizing_config()
    assert isinstance(cfg, SizingConfig)
    assert cfg.risk_per_trade_pct == 0.005
    assert cfg.min_notional == Decimal("10")


def test_settings_rejects_bad_sizing_params() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, sizing_risk_per_trade_pct=2.0)
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, sizing_max_simultaneous_positions=0)
