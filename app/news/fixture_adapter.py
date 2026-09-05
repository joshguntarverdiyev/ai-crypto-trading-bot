"""Offline, deterministic news source (Phase 5).

Returns injected ``NewsItemRaw`` items — no network, no I/O. Can simulate a
source outage by construction to exercise the conservative fail-safe path.
"""

from __future__ import annotations

from datetime import datetime

from app.exceptions import NewsSourceError
from app.news.adapter import NewsSourceAdapter
from app.news.models import NewsItemRaw


class FixtureNewsAdapter(NewsSourceAdapter):
    def __init__(
        self, items: list[NewsItemRaw] | None = None, *, fail: bool = False
    ) -> None:
        self._items = list(items or [])
        self._fail = fail

    def fetch(self, *, now: datetime, since: datetime | None = None) -> list[NewsItemRaw]:
        if self._fail:
            raise NewsSourceError("fixture news source is unavailable")
        return list(self._items)
