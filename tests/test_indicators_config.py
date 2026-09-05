"""Indicator/regime config invariants (IndicatorConfig, RegimeConfig, Settings)."""

from __future__ import annotations

import pytest

from app.config import load_settings
from app.exceptions import ConfigError
from app.indicators.config import IndicatorConfig
from app.regime.config import RegimeConfig


def test_indicator_config_requires_short_lt_long() -> None:
    with pytest.raises(ValueError):
        IndicatorConfig(ema_short=200, ema_long=50)
    with pytest.raises(ValueError):
        IndicatorConfig(ema_short=50, ema_long=50)
    with pytest.raises(ValueError):
        IndicatorConfig(rsi_period=0)


def test_regime_config_requires_low_lt_high() -> None:
    with pytest.raises(ValueError):
        RegimeConfig(vol_low_pct=0.02, vol_high_pct=0.005)
    with pytest.raises(ValueError):
        RegimeConfig(trend_band=0)


def test_settings_defaults_and_builders() -> None:
    s = load_settings(_env_file=None)
    assert (s.ema_short, s.ema_long, s.rsi_period, s.atr_period) == (50, 200, 14, 14)
    assert s.indicator_config().ema_long == 200
    assert s.regime_config().vol_high_pct == 0.02


def test_settings_reject_bad_ema_order() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, ema_short=200, ema_long=50)


def test_settings_reject_bad_vol_order() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, regime_vol_low_pct=0.02, regime_vol_high_pct=0.005)
