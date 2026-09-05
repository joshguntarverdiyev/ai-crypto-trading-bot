"""NewsService — the single consumption point for the analyst (Phase 5).

Orchestrates: fetch (adapter) → normalize → dedup → apply the §7 availability
gate for a given ``decision_time`` → return an audit-complete ``NewsContext``.
Mirrors ``MarketDataService``: data-quality problems are returned in the result
(``issues``); only adapter infrastructure failure raises (``NewsSourceError``).

Availability gate (Master Plan §7, §0.1-3), applied per item:

* unknown availability + ``require_known_availability`` → excluded
  (``UNKNOWN_AVAILABILITY``).
* ``available_at > decision_time`` → excluded (``FUTURE_AVAILABILITY``) —
  anti-look-ahead.
* ``decision_time - published_at > max_news_age`` → stale (``STALE``), not fresh.
* otherwise usable.

Overall availability is conservative: no items → UNAVAILABLE; ≥1 fresh usable →
AVAILABLE; in-gate but all stale → STALE; else → DEGRADED.
"""

from __future__ import annotations

from datetime import datetime

from app.news.adapter import NewsSourceAdapter
from app.news.config import NEWS_PIPELINE_VERSION, NewsConfig
from app.news.dedup import dedup_news
from app.news.models import (
    NewsAvailability,
    NewsContext,
    NewsIssue,
    NewsItem,
    NewsReason,
)
from app.news.normalization import normalize_news
from app.time_utils import ensure_utc


class NewsService:
    def __init__(
        self, adapter: NewsSourceAdapter, config: NewsConfig | None = None
    ) -> None:
        self._adapter = adapter
        self._cfg = config or NewsConfig()

    def build_context(
        self,
        *,
        decision_time: datetime,
        now: datetime,
        since: datetime | None = None,
    ) -> NewsContext:
        cfg = self._cfg
        dt = ensure_utc(decision_time)

        # Adapter infra failure propagates (NewsSourceError); the runtime maps it
        # to a conservative HOLD (§0.1-3).
        raw = self._adapter.fetch(now=now, since=since)

        items, issues_norm = normalize_news(raw, now=now, config=cfg)
        items, issues_dedup = dedup_news(items, config=cfg)
        issues: list[NewsIssue] = [*issues_norm, *issues_dedup]

        usable: list[NewsItem] = []
        in_gate_stale = False
        for item in items:
            if cfg.require_known_availability and not item.availability_known:
                issues.append(
                    NewsIssue(NewsReason.UNKNOWN_AVAILABILITY, "excluded", item.source_id)
                )
                continue
            if item.available_at > dt:
                issues.append(
                    NewsIssue(NewsReason.FUTURE_AVAILABILITY, "excluded", item.source_id)
                )
                continue
            if dt - item.published_at > cfg.max_news_age:
                in_gate_stale = True
                issues.append(NewsIssue(NewsReason.STALE, "stale", item.source_id))
                continue
            usable.append(item)

        if not raw:
            availability, reason = NewsAvailability.UNAVAILABLE, NewsReason.UNAVAILABLE
        elif usable:
            availability, reason = NewsAvailability.AVAILABLE, NewsReason.OK
        elif in_gate_stale:
            availability, reason = NewsAvailability.STALE, NewsReason.STALE
        else:
            availability, reason = NewsAvailability.DEGRADED, NewsReason.UNKNOWN_AVAILABILITY

        sources = tuple(dict.fromkeys(item.source for item in items))
        return NewsContext(
            decision_time=dt,
            items=tuple(usable),
            availability=availability,
            reason=reason,
            issues=tuple(issues),
            sources=sources,
            news_pipeline_version=NEWS_PIPELINE_VERSION,
        )
