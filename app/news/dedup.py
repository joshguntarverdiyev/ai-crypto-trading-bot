"""Deterministic news de-duplication (Phase 5).

First-seen wins: iterating in input order, an item is a duplicate of an earlier
kept item when it shares a ``dedup_key`` and its ``published_at`` is within
``dedup_window`` of that item. Duplicates are dropped and flagged; the retained
set preserves input order.
"""

from __future__ import annotations

from app.news.config import NewsConfig
from app.news.models import NewsIssue, NewsItem, NewsReason


def dedup_news(
    items: list[NewsItem], *, config: NewsConfig
) -> tuple[list[NewsItem], list[NewsIssue]]:
    kept: list[NewsItem] = []
    kept_by_key: dict[str, NewsItem] = {}
    issues: list[NewsIssue] = []

    for item in items:
        prior = kept_by_key.get(item.dedup_key)
        if prior is not None:
            within = abs(item.published_at - prior.published_at) <= config.dedup_window
            if within:
                issues.append(
                    NewsIssue(NewsReason.DEDUP_DROPPED, "duplicate", item.source_id)
                )
                continue
        kept.append(item)
        kept_by_key[item.dedup_key] = item
    return kept, issues
