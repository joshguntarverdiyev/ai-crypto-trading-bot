"""P9 news multi-symbol coverage + single-instance poller lock (offline)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config import load_settings
from app.news.config import NewsConfig
from app.news.ingestion import acquire_ingest_lock, release_ingest_lock
from app.news.models import NewsItemRaw
from app.news.normalization import normalize_news


# --- A. universe → news ticker/known-asset propagation (dynamic, not hardcoded) ---
def test_default_universe_is_btc_eth_unchanged() -> None:
    s = load_settings(_env_file=None)
    assert s.universe_base_assets() == ("BTC", "ETH")
    assert s.crypto_news_config().tickers == ("BTC", "ETH")
    assert s.news_config().known_assets == ("BTC", "ETH")


def test_arbitrary_universe_propagates_to_tickers_and_known_assets() -> None:
    s = load_settings(
        _env_file=None, news_known_assets=[],  # isolate the universe-derived part
        market_symbols=["SOL/USDT", "XRP/USDT", "BTC/USDT", "PEPE/USDT", "SOL/USDT"],
    )
    bases = s.universe_base_assets()
    assert bases == ("SOL", "XRP", "BTC", "PEPE")  # deduped, order-preserving, not hardcoded
    assert s.crypto_news_config().tickers == bases
    assert set(s.news_config().known_assets) == {"SOL", "XRP", "BTC", "PEPE"}


def test_news_config_unions_explicit_and_universe_assets() -> None:
    s = load_settings(
        _env_file=None, news_known_assets=["BTC", "ETH"],
        market_symbols=["SOL/USDT", "ADA/USDT"],
    )
    assert set(s.news_config().known_assets) == {"BTC", "ETH", "SOL", "ADA"}


# --- B. multi-symbol normalization + safe ignoring of unknown assets ---------------
def _raw(sym_assets, title="t"):
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    return NewsItemRaw(source="cryptonewsapi", source_id=f"id-{title}", title=title,
                       published_at=now, available_at=now, discovered_at=now, assets=sym_assets)


def test_normalization_keeps_universe_assets_and_ignores_unknown() -> None:
    cfg = NewsConfig(known_assets=("BTC", "ETH", "SOL", "XRP"))
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    raws = [
        _raw(("BTC",), "btc"), _raw(("ETH",), "eth"), _raw(("SOL",), "sol"),
        _raw(("XRP", "SOL"), "xrpsol"), _raw(("DOGE",), "doge"),  # DOGE not known → ignored
    ]
    items, _issues = normalize_news(raws, now=now, config=cfg)
    kept = {a for it in items for a in it.affected_assets}
    assert {"BTC", "ETH", "SOL", "XRP"} <= kept
    assert "DOGE" not in kept  # non-universe asset safely ignored


def test_pair_symbol_normalizes_to_base_via_universe_base_assets() -> None:
    s = load_settings(_env_file=None, market_symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    # pair "BTC/USDT" → base "BTC" (used for news tickers/known-assets)
    assert s.universe_base_assets() == ("BTC", "ETH", "SOL")


# --- C. single-instance poller lock -----------------------------------------------
def test_second_poller_instance_is_refused(tmp_path) -> None:
    lock_path = f"{tmp_path}/news_ingest.db.lock"
    first = acquire_ingest_lock(lock_path)
    assert first is not None
    second = acquire_ingest_lock(lock_path)  # another live instance
    assert second is None  # refused
    release_ingest_lock(first)
    # after release, a fresh instance (restart) can acquire again
    third = acquire_ingest_lock(lock_path)
    assert third is not None
    release_ingest_lock(third)


def test_locked_run_makes_zero_api_calls(tmp_path, monkeypatch) -> None:
    from scripts import run_news_ingest

    # Any HTTP call would fail the test — a locked second instance must never poll.
    def boom(*a, **k):
        raise AssertionError("locked instance must NOT make an API call")

    monkeypatch.setattr("httpx.get", boom)
    s = load_settings(
        _env_file=None, crypto_news_api_token="X",
        news_ingest_db_path=f"{tmp_path}/news_ingest.db",
    )
    held = acquire_ingest_lock(f"{tmp_path}/news_ingest.db.lock")  # simulate running instance
    assert held is not None
    try:
        rc = run_news_ingest.run(s, iterations=3, supervise=False)  # second instance
        assert rc == 0  # exits cleanly, zero API calls (boom never raised)
    finally:
        release_ingest_lock(held)


def test_release_handles_none() -> None:
    release_ingest_lock(None)  # no-op, never raises


# --- D. token redaction unchanged (config path still lists the token as a secret) --
def test_token_still_registered_for_redaction() -> None:
    s = load_settings(_env_file=None, crypto_news_api_token="SECRET-XYZ")
    assert "SECRET-XYZ" in s.secret_values()


def test_httpx_not_imported_by_locked_run(tmp_path, monkeypatch) -> None:
    # sanity: the locked path returns before building the adapter/store
    import sys

    from scripts import run_news_ingest

    monkeypatch.setattr("httpx.get", lambda *a, **k: pytest.fail("no call expected"))
    s = load_settings(_env_file=None, crypto_news_api_token="X",
                      news_ingest_db_path=f"{tmp_path}/n.db")
    held = acquire_ingest_lock(f"{tmp_path}/n.db.lock")
    try:
        assert run_news_ingest.run(s, iterations=1, supervise=False) == 0
    finally:
        release_ingest_lock(held)
    assert "ccxt" not in sys.modules  # unrelated heavy deps never pulled
