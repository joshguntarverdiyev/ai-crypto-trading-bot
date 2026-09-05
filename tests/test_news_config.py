"""NewsConfig invariants, version tag, and Settings.news_config()."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import load_settings
from app.exceptions import ConfigError
from app.news.config import NEWS_PIPELINE_VERSION, NewsConfig


def test_defaults_are_valid_and_versioned() -> None:
    cfg = NewsConfig()
    assert cfg.version_tag.startswith(NEWS_PIPELINE_VERSION)
    assert cfg.require_known_availability is True
    assert "BTC" in cfg.known_assets


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_news_age": timedelta(0)},
        {"dedup_window": timedelta(seconds=-1)},
        {"known_assets": ()},
        {"known_assets": ("btc",)},  # not upper
        {"known_assets": ("BT-C",)},  # not alnum
    ],
)
def test_rejects_bad_params(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        NewsConfig(**kwargs)


def test_settings_builds_news_config() -> None:
    s = load_settings(_env_file=None)
    cfg = s.news_config()
    assert isinstance(cfg, NewsConfig)
    assert cfg.max_news_age == timedelta(seconds=86400)
    assert cfg.known_assets == ("BTC", "ETH")


def test_settings_rejects_bad_news_params() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, news_max_age_seconds=0)
