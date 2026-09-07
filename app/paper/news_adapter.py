"""Centralized conservative news-availability adapter (Phase 9, §35.8).

Wraps any frozen P5 ``NewsSourceAdapter`` and assigns each item's ``available_at``
as the CENTRAL availability authority:

    available_at = max(published_at + settle_seconds, first_seen_at)

where ``first_seen_at`` is the item's ``discovered_at`` (Tier-2 ingestion records
the genuine earliest observation; falls back to ``published_at`` when absent).
Because the frozen ``NewsService`` gate excludes items whose
``available_at > decision_time``, this makes P9 news strictly MORE conservative
than the raw feed on BOTH axes: an item is available no earlier than the
settle-delayed publish time AND no earlier than we actually first saw it —
preventing discovery-lag over-admission near a boundary and preserving
no-look-ahead. It never over-admits and never fabricates availability: when
``published_at`` is unknown the item is left untouched (``NewsService`` flags it).
``available_at <= decision_time`` continues to hold honestly. The margin is
pre-registered and recorded in the run's config snapshot.

Backward-compatible: for a legacy item with ``available_at == published_at`` and no
separate ``discovered_at``, the result is ``published_at + settle`` — identical to
the prior shift-only behavior.
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
        out: list[NewsItemRaw] = []
        for item in raw:
            published = item.published_at
            if published is None:
                # No usable event time → do not fabricate availability; the frozen
                # NewsService normalization/gate handles it (NO_TIMESTAMP/UNKNOWN).
                out.append(item)
                continue
            first_seen = item.discovered_at if item.discovered_at is not None else published
            available_at = max(published + self._delta, first_seen)
            out.append(replace(item, available_at=available_at))
        return out
