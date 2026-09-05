"""RiskConfig + PaperConfig invariants and Settings builders."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import load_settings
from app.exceptions import ConfigError
from app.execution.config import PAPER_VERSION, PaperConfig
from app.risk.config import RISK_VERSION, RiskConfig


def test_risk_defaults_valid_and_versioned() -> None:
    cfg = RiskConfig()
    assert cfg.version_tag.startswith(RISK_VERSION)
    assert cfg.correlation_group_for("BTC") == frozenset({"BTC", "ETH"})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_risk_per_trade_pct": 0.0},
        {"max_drawdown_pct": 1.5},
        {"max_simultaneous_positions": 0},
        {"max_staleness_intervals": -1},
    ],
)
def test_risk_rejects_bad_params(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        RiskConfig(**kwargs)


def test_paper_defaults_valid_and_versioned() -> None:
    cfg = PaperConfig()
    assert cfg.version_tag.startswith(PAPER_VERSION)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tick_size": Decimal("0")},
        {"min_notional": Decimal("-1")},
        {"starting_equity": Decimal("0")},
        {"taker_fee_pct": -0.1},
    ],
)
def test_paper_rejects_bad_params(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        PaperConfig(**kwargs)


def test_settings_build_risk_and_paper() -> None:
    s = load_settings(_env_file=None)
    assert isinstance(s.risk_config(), RiskConfig)
    assert isinstance(s.paper_config(), PaperConfig)
    assert s.paper_config().starting_equity == Decimal("10000")


def test_settings_reject_bad_risk_params() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, risk_max_drawdown_pct=2.0)


def test_live_trading_still_false() -> None:
    assert load_settings(_env_file=None).live_trading is False
