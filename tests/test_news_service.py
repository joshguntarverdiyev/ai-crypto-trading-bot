"""NewsService end-to-end: context assembly, provenance, source-failure raise."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.exceptions import NewsSourceError
from app.news.config import NewsConfig
from app.news.fixture_adapter import FixtureNewsAdapter
from app.news.models import NewsAvailability, NewsItemRaw
from app.news.service import NewsService

DT = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


def test_context_carries_provenance_and_version() -> None:
    avail = DT - timedelta(hours=1)
    items = [
        NewsItemRaw(
            source="rssA", source_id="1", title="t1", published_at=avail, available_at=avail
        ),
        NewsItemRaw(
            source="rssB", source_id="2", title="t2", published_at=avail, available_at=avail
        ),
    ]
    ctx = NewsService(FixtureNewsAdapter(items), NewsConfig()).build_context(
        decision_time=DT, now=DT
    )
    assert ctx.availability is NewsAvailability.AVAILABLE
    assert set(ctx.sources) == {"rssA", "rssB"}
    assert ctx.news_pipeline_version == "news-v1"


def test_source_infra_failure_raises() -> None:
    svc = NewsService(FixtureNewsAdapter(fail=True), NewsConfig())
    with pytest.raises(NewsSourceError):
        svc.build_context(decision_time=DT, now=DT)
