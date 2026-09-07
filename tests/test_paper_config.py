"""P9 config: fail-closed flag matrix + conservative news settle margin."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.ai.fixture_provider import FixtureAnalystProvider
from app.exceptions import ConfigError
from app.news.fixture_adapter import FixtureNewsAdapter
from app.news.models import NewsItemRaw
from app.paper.build import build_paper_system
from app.paper.news_adapter import SettleMarginNewsAdapter
from tests._p9_helpers import APPROVE, fixture_adapter, main_factory, news_adapter, paper_settings


def _build(settings):
    return build_paper_system(
        settings, main_factory(settings), market_adapter=fixture_adapter(),
        news_adapter=news_adapter(), analyst_provider=FixtureAnalystProvider(APPROVE),
    )


def test_valid_combo_starts(tmp_path) -> None:
    # (live_trading=False, paper_trading=False, paper_validation_enabled=True)
    runner, run_id = _build(paper_settings(tmp_path))
    assert run_id


def test_disabled_flag_refuses(tmp_path) -> None:
    with pytest.raises(ConfigError):
        _build(paper_settings(tmp_path, paper_validation_enabled=False))


def test_paper_trading_true_refuses(tmp_path) -> None:
    with pytest.raises(ConfigError):
        _build(paper_settings(tmp_path, paper_trading=True))


def test_live_trading_true_fails_closed_at_load(tmp_path) -> None:
    # live_trading=True cannot even be constructed (Phase 0 safety) — fail-closed.
    with pytest.raises(ConfigError):
        paper_settings(tmp_path, live_trading=True)


def test_enable_flag_does_not_mutate_execution_flags(tmp_path) -> None:
    s = paper_settings(tmp_path)
    assert s.paper_validation_enabled is True
    assert s.live_trading is False
    assert s.paper_trading is False


def test_news_settle_margin_shifts_available_at() -> None:
    t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    inner = FixtureNewsAdapter([
        NewsItemRaw(source="fixture", source_id="x", title="t",
                    published_at=t, available_at=t, assets=("BTC",))
    ])
    adapter = SettleMarginNewsAdapter(inner, settle_seconds=120)
    out = adapter.fetch(now=t)
    assert out[0].available_at == t + timedelta(seconds=120)


def test_news_settle_margin_zero_is_noop() -> None:
    t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    inner = FixtureNewsAdapter([
        NewsItemRaw(source="fixture", source_id="x", title="t",
                    published_at=t, available_at=t, assets=("BTC",))
    ])
    out = SettleMarginNewsAdapter(inner, settle_seconds=0).fetch(now=t)
    assert out[0].available_at == t
