"""News models (Phase 5).

Two layers, mirroring the Phase 1 market-data boundary:

* ``NewsItemRaw`` — UNTRUSTED adapter DTO (permissive; missing/bad fields become
  data-quality issues, never exceptions).
* ``NewsItem`` — STRICT canonical item: the five timestamps (Master Plan §7) are
  timezone-aware UTC. ``processed_at`` is ``None`` until an analyst/sentiment step
  processes it.

``NewsContext`` is the availability-gated set assembled for a specific
``decision_time`` — the only thing the analyst consumes. Availability is never
optimistic: absence/unknown/staleness is conservative (§0.1-3), never "no
negative news".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class NewsAvailability(StrEnum):
    AVAILABLE = "available"  # >= 1 fresh, known-available item usable at decision_time
    STALE = "stale"  # items in-gate but all older than max_news_age
    DEGRADED = "degraded"  # items exist but all excluded (unknown/future availability)
    UNAVAILABLE = "unavailable"  # no items at all — zero information


class NewsReason(StrEnum):
    OK = "ok"
    NO_TIMESTAMP = "no_timestamp"
    UNKNOWN_AVAILABILITY = "unknown_availability"
    FUTURE_AVAILABILITY = "future_availability"  # available_at > decision_time (look-ahead)
    STALE = "stale"
    DEDUP_DROPPED = "dedup_dropped"
    MALFORMED = "malformed"
    UNAVAILABLE = "unavailable"


def _require_utc(name: str, dt: datetime) -> None:
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")


@dataclass(frozen=True)
class NewsItemRaw:
    """Untrusted news candidate from a source adapter (pre-normalization)."""

    source: str
    source_id: str | None = None
    url: str | None = None
    title: str | None = None
    summary: str | None = None
    published_at: datetime | None = None
    discovered_at: datetime | None = None
    available_at: datetime | None = None  # true source availability, if known
    assets: tuple[str, ...] = ()


@dataclass(frozen=True)
class NewsItem:
    """Strict canonical news item (tz-aware UTC; five-timestamp model, §7)."""

    source: str
    source_id: str
    url: str | None
    title: str
    summary: str
    published_at: datetime
    discovered_at: datetime
    ingested_at: datetime
    available_at: datetime
    processed_at: datetime | None
    availability_known: bool  # False → historical availability was not provided
    affected_assets: tuple[str, ...]
    trust: float  # provenance trust in [0, 1]; lowered when availability unknown
    dedup_key: str
    news_pipeline_version: str

    def __post_init__(self) -> None:
        _require_utc("published_at", self.published_at)
        _require_utc("discovered_at", self.discovered_at)
        _require_utc("ingested_at", self.ingested_at)
        _require_utc("available_at", self.available_at)
        if self.processed_at is not None:
            _require_utc("processed_at", self.processed_at)


@dataclass(frozen=True)
class NewsIssue:
    code: NewsReason
    detail: str
    source_id: str | None = None


@dataclass(frozen=True)
class NewsContext:
    """Availability-gated news for one decision (the analyst's input)."""

    decision_time: datetime
    items: tuple[NewsItem, ...]  # usable: known-available, in-gate, fresh
    availability: NewsAvailability
    reason: NewsReason
    issues: tuple[NewsIssue, ...]
    sources: tuple[str, ...]  # provenance of fetched items
    news_pipeline_version: str
