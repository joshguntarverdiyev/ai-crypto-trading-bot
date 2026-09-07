"""Tier-2 Crypto News API ingestion poller (Phase 9) — NO trading, NO decisions.

Continuously polls the Crypto News API and records each article's genuine
``first_seen_at`` + ingestion provenance into the isolated ingestion store
(``news_ingest_db_path``). The P9 runner reads that store at decision time, so
``first_seen_at`` is defensible no-look-ahead evidence rather than "fetch == now".

This process places NO orders, runs NO strategy/risk/Claude pipeline, and writes
ONLY to the isolated ingestion DB. The API token comes from config, is never
logged, and never appears in provenance/errors.

Usage::

    python -m scripts.run_news_ingest                 # one poll, then exit
    python -m scripts.run_news_ingest --iterations 4  # four polls (sleeps between)
    python -m scripts.run_news_ingest --supervise     # 15-min loop until stopped
"""

from __future__ import annotations

import argparse
import logging
import signal

from app.config import load_settings
from app.logging_config import configure_logging
from app.news.cryptonews_adapter import CryptoNewsApiAdapter
from app.news.ingestion import NewsIngestionStore, make_news_ingest_store
from app.time_utils import utc_now

log = logging.getLogger("scripts.run_news_ingest")


def poll_once(adapter: CryptoNewsApiAdapter, store: NewsIngestionStore) -> tuple[int, int, int]:
    """One poll → upsert. Returns (fetched, inserted, updated). Never logs the token."""
    now = utc_now()
    result = adapter.fetch_result(now=now)
    stats = store.upsert_articles(
        result.articles, fetched_at=now, http_status=result.http_status,
        response_hash=result.response_hash, request_params=result.request_params,
    )
    log.info(
        "news ingest: fetched=%d inserted=%d updated=%d rejects=%d http=%s",
        len(result.articles), stats.inserted, stats.updated, len(result.rejects),
        result.http_status,
    )
    return len(result.articles), stats.inserted, stats.updated


def _install_graceful_stop() -> None:
    def _handler(signum, _frame):  # noqa: ANN001, ANN202
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGTERM, _handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Crypto News API ingestion poller (Phase 9).")
    parser.add_argument("--iterations", type=int, default=1, help="polls to run (finite mode)")
    parser.add_argument("--supervise", action="store_true", help="loop on the poll interval")
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings)

    cfg = settings.crypto_news_config()
    # Fail-closed: CryptoNewsApiAdapter raises if the token is empty (never invented).
    adapter = CryptoNewsApiAdapter(cfg)
    store = make_news_ingest_store(settings.news_ingest_db_path)
    interval = settings.crypto_news_poll_seconds
    log.info("news ingest start: db=%s interval=%ss supervise=%s (token redacted)",
             settings.news_ingest_db_path, interval, args.supervise)

    import time as _time

    try:
        if args.supervise:
            _install_graceful_stop()
            while True:
                poll_once(adapter, store)
                _time.sleep(interval)
        else:
            for i in range(max(1, args.iterations)):
                poll_once(adapter, store)
                if i + 1 < max(1, args.iterations):
                    _time.sleep(interval)
    except KeyboardInterrupt:
        log.info("news ingest stop requested: shutting down gracefully")

    log.info("news ingest done (no orders, no decisions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
