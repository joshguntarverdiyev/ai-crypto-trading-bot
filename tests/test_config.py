"""Configuration: safe defaults, normalization, and fail-closed validation."""

from __future__ import annotations

import pytest

from app.config import Environment, load_settings
from app.exceptions import ConfigError


def test_defaults_are_safe() -> None:
    s = load_settings(_env_file=None)
    assert s.live_trading is False
    assert s.paper_trading is False
    assert s.shadow_mode is False
    assert s.environment is Environment.DEVELOPMENT
    assert s.log_level == "INFO"
    assert s.database_url.startswith("sqlite:///")


def test_credential_placeholders_are_empty() -> None:
    s = load_settings(_env_file=None)
    assert s.exchange_api_key == ""
    assert s.exchange_api_secret == ""
    assert s.anthropic_api_key == ""
    assert s.telegram_bot_token == ""
    assert s.telegram_chat_id == ""
    assert s.secret_values() == []


def test_log_level_is_normalized() -> None:
    assert load_settings(_env_file=None, log_level="debug").log_level == "DEBUG"


def test_invalid_log_level_fails_closed() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, log_level="TRACE")


def test_live_trading_true_is_rejected() -> None:
    # Phase 0 has no execution layer; enabling live trading must fail at load.
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, live_trading=True)
