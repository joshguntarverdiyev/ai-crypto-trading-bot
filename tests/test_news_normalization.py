"""News normalization: 5-timestamp model, tz-UTC, assets, provenance/trust."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.news.config import NewsConfig
from app.news.models import NewsItem, NewsItemRaw, NewsReason
from app.news.normalization import normalize_news

NOW = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
CFG = NewsConfig()


def test_full_item_keeps_known_availability_and_assets() -> None:
    pub = NOW - timedelta(hours=1)
    raw = NewsItemRaw(
        source="fixture", source_id="a1", url="http://x/a1", title=" Big BTC news ",
        summary="body", published_at=pub, available_at=pub, assets=("btc", "xrp", "BTC"),
    )
    items, issues = normalize_news([raw], now=NOW, config=CFG)
    assert len(items) == 1
    item = items[0]
    assert item.ingested_at == NOW
    assert item.available_at == pub and item.availability_known is True
    assert item.trust == 1.0
    assert item.title == "Big BTC news"  # trimmed
    assert item.affected_assets == ("BTC",)  # known-only, deduped, uppercased
    assert item.processed_at is None
    assert issues == []


def test_unknown_availability_is_flagged_and_trust_lowered() -> None:
    raw = NewsItemRaw(
        source="fixture", source_id="a2", title="t",
        published_at=NOW - timedelta(hours=2),  # no available_at provided
    )
    items, issues = normalize_news([raw], now=NOW, config=CFG)
    assert items[0].availability_known is False
    assert items[0].trust == 0.5
    assert any(i.code is NewsReason.UNKNOWN_AVAILABILITY for i in issues)


def test_no_timestamp_falls_back_to_ingested_and_flags() -> None:
    raw = NewsItemRaw(source="fixture", source_id="a3", title="t")  # no timestamps
    items, issues = normalize_news([raw], now=NOW, config=CFG)
    assert items[0].published_at == NOW
    assert any(i.code is NewsReason.NO_TIMESTAMP for i in issues)


def test_malformed_missing_title_skipped() -> None:
    items, issues = normalize_news(
        [NewsItemRaw(source="fixture", source_id="a4", title=None)], now=NOW, config=CFG
    )
    assert items == []
    assert any(i.code is NewsReason.MALFORMED for i in issues)


def test_naive_timestamp_is_tagged_utc() -> None:
    naive = datetime(2026, 1, 2, 10, 0)  # no tzinfo
    raw = NewsItemRaw(
        source="fixture", source_id="a5", title="t", published_at=naive, available_at=naive
    )
    items, _ = normalize_news([raw], now=NOW, config=CFG)
    assert items[0].published_at.tzinfo is not None
    assert items[0].published_at == datetime(2026, 1, 2, 10, 0, tzinfo=UTC)


def test_newsitem_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        NewsItem(
            source="s", source_id="i", url=None, title="t", summary="",
            published_at=datetime(2026, 1, 1),  # naive
            discovered_at=NOW, ingested_at=NOW, available_at=NOW, processed_at=None,
            availability_known=True, affected_assets=(), trust=1.0,
            dedup_key="k", news_pipeline_version="news-v1",
        )
