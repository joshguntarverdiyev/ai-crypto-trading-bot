"""Normalize untrusted NewsItemRaw → strict NewsItem (Phase 5).

Deterministic. Data-quality problems become ``NewsIssue`` records (mirroring
``app/market_data/validation.py``), never exceptions. The five-timestamp model
(Master Plan §7) is assigned here:

* ``ingested_at`` — always the injected ``now`` (when *we* received it).
* ``available_at`` / ``availability_known`` — the source's true availability if
  provided; otherwise availability is UNKNOWN (``availability_known=False``) and
  a conservative placeholder (``ingested_at``) is stored. The gate (service)
  excludes unknown-availability items when configured — never assumes a past
  item was historically available (anti-look-ahead).
* ``processed_at`` — ``None`` here (set by a later analyst/sentiment step).
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.news.config import NEWS_PIPELINE_VERSION, NewsConfig
from app.news.models import NewsIssue, NewsItem, NewsItemRaw, NewsReason
from app.time_utils import ensure_utc


def _dedup_key(source: str, source_id: str | None, url: str | None, title: str) -> str:
    basis = source_id or url or f"{source}:{title.strip().lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def _resolve_assets(raw_assets: tuple[str, ...], config: NewsConfig) -> tuple[str, ...]:
    known = set(config.known_assets)
    seen: list[str] = []
    for tag in raw_assets:
        upper = tag.strip().upper()
        if upper in known and upper not in seen:
            seen.append(upper)
    return tuple(seen)


def normalize_news(
    raw_items: list[NewsItemRaw], *, now: datetime, config: NewsConfig
) -> tuple[list[NewsItem], list[NewsIssue]]:
    ingested_at = ensure_utc(now)
    items: list[NewsItem] = []
    issues: list[NewsIssue] = []

    for raw in raw_items:
        if not raw.source or not raw.title or not raw.title.strip():
            issues.append(
                NewsIssue(NewsReason.MALFORMED, "missing source/title", raw.source_id)
            )
            continue

        published = ensure_utc(raw.published_at) if raw.published_at else None
        discovered = ensure_utc(raw.discovered_at) if raw.discovered_at else published

        if published is None:
            # No usable event time: keep the item but flag it; fall back to
            # ingestion time. Availability is therefore unknown.
            published = ingested_at
            discovered = discovered or ingested_at
            issues.append(NewsIssue(NewsReason.NO_TIMESTAMP, "no published_at", raw.source_id))
        assert discovered is not None

        if raw.available_at is not None:
            available_at = ensure_utc(raw.available_at)
            availability_known = True
        else:
            # Historical availability was not provided → UNKNOWN. Store a
            # conservative placeholder; the gate excludes it when configured.
            available_at = ingested_at
            availability_known = False
            issues.append(
                NewsIssue(NewsReason.UNKNOWN_AVAILABILITY, "no available_at", raw.source_id)
            )

        source_id = raw.source_id or _dedup_key(raw.source, None, raw.url, raw.title)
        items.append(
            NewsItem(
                source=raw.source,
                source_id=source_id,
                url=raw.url,
                title=raw.title.strip(),
                summary=(raw.summary or "").strip(),
                published_at=published,
                discovered_at=discovered,
                ingested_at=ingested_at,
                available_at=available_at,
                processed_at=None,
                availability_known=availability_known,
                affected_assets=_resolve_assets(raw.assets, config),
                trust=1.0 if availability_known else 0.5,
                dedup_key=_dedup_key(raw.source, raw.source_id, raw.url, raw.title),
                news_pipeline_version=NEWS_PIPELINE_VERSION,
            )
        )
    return items, issues
