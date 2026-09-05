"""News-pipeline configuration and version tag (Phase 5 — source of truth).

Deterministic, offline. Governs freshness, the availability gate, dedup, and
affected-asset resolution (Master Plan §7, §0.1-3). All thresholds are
provisional, versioned config — NOT calibrated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

NEWS_PIPELINE_VERSION = "news-v1"


@dataclass(frozen=True)
class NewsConfig:
    """Freshness/availability/dedup parameters for the news pipeline."""

    max_news_age: timedelta = timedelta(hours=24)  # older than this = STALE
    dedup_window: timedelta = timedelta(hours=48)  # same key within window = dup
    # Fail-safe (§7): when an item's historical availability is unknown, exclude
    # it from the usable set rather than assume it was available.
    require_known_availability: bool = True
    known_assets: tuple[str, ...] = ("BTC", "ETH")

    def __post_init__(self) -> None:
        if self.max_news_age <= timedelta(0):
            raise ValueError("max_news_age must be > 0")
        if self.dedup_window <= timedelta(0):
            raise ValueError("dedup_window must be > 0")
        if not self.known_assets:
            raise ValueError("known_assets must be non-empty")
        for asset in self.known_assets:
            if not asset.isalnum() or not asset.isupper():
                raise ValueError(f"known_assets entries must be UPPER alnum: {asset!r}")

    @property
    def version_tag(self) -> str:
        return (
            f"{NEWS_PIPELINE_VERSION}|age{int(self.max_news_age.total_seconds())}"
            f"|dw{int(self.dedup_window.total_seconds())}"
            f"|rka{int(self.require_known_availability)}"
            f"|assets{'/'.join(self.known_assets)}"
        )
