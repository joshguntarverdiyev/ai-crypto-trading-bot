"""Conservative news availability adapter (Phase 9, §35.8).

Wraps any frozen P5 ``NewsSourceAdapter`` and pushes each item's ``available_at``
forward by a configured settle margin. Because the frozen ``NewsService`` gate
excludes items whose ``available_at > decision_time``, this makes P9 news strictly
MORE conservative than the raw feed: an item published just before a boundary
(within the margin) is not admitted until the margin has elapsed, preventing
discovery-lag over-admission near the boundary. It never over-admits and never
fabricates availability; ``available_at <= decision_time`` continues to hold
honestly. The margin is pre-registered and recorded in the run's config snapshot.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from app.news.adapter import NewsSourceAdapter
from app.news.models import NewsItemRaw


class SettleMarginNewsAdapter(NewsSourceAdapter):
    def __init__(self, inner: NewsSourceAdapter, *, settle_seconds: int) -> None:
        if settle_seconds < 0:
            raise ValueError("settle_seconds must be >= 0")
        self._inner = inner
        self._delta = timedelta(seconds=settle_seconds)

    def fetch(self, *, now: datetime, since: datetime | None = None) -> list[NewsItemRaw]:
        raw = self._inner.fetch(now=now, since=since)
        if self._delta.total_seconds() == 0:
            return raw
        shifted: list[NewsItemRaw] = []
        for item in raw:
            if item.available_at is not None:
                shifted.append(replace(item, available_at=item.available_at + self._delta))
            else:
                shifted.append(item)
        return shifted
