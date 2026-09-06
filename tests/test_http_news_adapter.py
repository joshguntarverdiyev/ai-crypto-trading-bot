"""Phase 8 CryptoPanic news adapter — contract-bound converter (offline).

Tests the pure converter only (no network): five timestamps preserved, asset
tagging, forward-only available_at = publish time, and malformed-shape → error
(never a valid-empty result).
"""

from __future__ import annotations

import pytest

from app.exceptions import NewsSourceError
from app.news.config import NewsConfig
from app.news.http_adapter import raw_items_from_cryptopanic
from app.news.normalization import normalize_news
from app.time_utils import utc_now


def test_converter_maps_fields_and_forward_only_availability() -> None:
    payload = {
        "results": [
            {
                "id": 42, "title": "BTC rallies", "url": "https://x/y",
                "published_at": "2026-09-06T12:00:00Z",
                "currencies": [{"code": "btc"}, {"code": "eth"}],
            }
        ]
    }
    items = raw_items_from_cryptopanic(payload)
    assert len(items) == 1
    item = items[0]
    assert item.source == "cryptopanic" and item.source_id == "42"
    assert item.published_at is not None and item.published_at == item.available_at  # §7.1 forward
    assert item.assets == ("BTC", "ETH")


def test_converter_preserves_five_timestamps_through_normalization() -> None:
    payload = {"results": [{"id": 1, "title": "t", "published_at": "2026-09-06T12:00:00Z",
                            "currencies": [{"code": "btc"}]}]}
    raw = raw_items_from_cryptopanic(payload)
    items, _issues = normalize_news(raw, now=utc_now(), config=NewsConfig())
    assert len(items) == 1
    n = items[0]
    for ts in (n.published_at, n.discovered_at, n.ingested_at, n.available_at):
        assert ts.tzinfo is not None  # tz-aware UTC five-timestamp model
    assert n.availability_known is True  # available_at was provided (= publish time)
    assert n.affected_assets == ("BTC",)


def test_malformed_payload_raises_not_valid_empty() -> None:
    with pytest.raises(NewsSourceError):
        raw_items_from_cryptopanic(["not", "a", "dict"])
    with pytest.raises(NewsSourceError):
        raw_items_from_cryptopanic({"results": "not-a-list"})


def test_missing_results_is_empty_list() -> None:
    assert raw_items_from_cryptopanic({}) == []
