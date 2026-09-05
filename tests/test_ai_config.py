"""AIConfig invariants, model-class resolution, and Settings.ai_config()."""

from __future__ import annotations

import pytest

from app.ai.config import AI_ANALYST_VERSION, AIConfig, ModelClass
from app.config import load_settings
from app.exceptions import ConfigError


def test_defaults_are_valid_and_versioned() -> None:
    cfg = AIConfig()
    assert cfg.version_tag.startswith(AI_ANALYST_VERSION)
    assert cfg.analyst_model_class is ModelClass.SONNET
    # analyst id resolves to the sonnet id (the exact runtime-recorded model_id)
    assert cfg.analyst_model_id == cfg.sonnet_model_id
    assert cfg.resolve_model_id(ModelClass.HAIKU) == cfg.haiku_model_id


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sonnet_model_id": ""},
        {"timeout_seconds": 0.0},
        {"uncertain_policy": "size_down"},  # only "hold" allowed in P5
    ],
)
def test_rejects_bad_params(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        AIConfig(**kwargs)


def test_settings_builds_ai_config() -> None:
    s = load_settings(_env_file=None)
    cfg = s.ai_config()
    assert isinstance(cfg, AIConfig)
    assert cfg.analyst_model_class is ModelClass.SONNET
    assert cfg.analyst_model_id == "claude-sonnet-4-6"


def test_settings_rejects_bad_ai_params() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, ai_analyst_model_class="gpt")
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, ai_uncertain_policy="proceed")
