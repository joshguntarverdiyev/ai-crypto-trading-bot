"""News de-duplication: first-seen wins, within the dedup window."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.news.config import NewsConfig
from app.news.fixture_adapter import FixtureNewsAdapter
from app.news.models import NewsAvailability, NewsItemRaw, NewsReason
from app.news.service import NewsService

DT = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


def _raw(source_id: str, minutes_ago: int) -> NewsItemRaw:
    ts = DT - timedelta(minutes=minutes_ago)
    return NewsItemRaw(
        source="fixture", source_id=source_id, title="dup", published_at=ts, available_at=ts
    )


def test_same_source_id_deduped_first_seen_wins() -> None:
    svc = NewsService(FixtureNewsAdapter([_raw("a", 10), _raw("a", 5)]), NewsConfig())
    ctx = svc.build_context(decision_time=DT, now=DT)
    assert len(ctx.items) == 1
    assert ctx.items[0].published_at == DT - timedelta(minutes=10)  # earliest kept
    assert any(i.code is NewsReason.DEDUP_DROPPED for i in ctx.issues)
    assert ctx.availability is NewsAvailability.AVAILABLE


def test_distinct_ids_not_deduped() -> None:
    svc = NewsService(FixtureNewsAdapter([_raw("a", 10), _raw("b", 5)]), NewsConfig())
    ctx = svc.build_context(decision_time=DT, now=DT)
    assert len(ctx.items) == 2
