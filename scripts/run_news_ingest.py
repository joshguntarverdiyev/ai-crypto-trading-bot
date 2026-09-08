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
from app.news.ingestion import (
    NewsIngestionStore,
    acquire_ingest_lock,
    make_news_ingest_store,
    release_ingest_lock,
)
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


def run(settings, *, iterations: int, supervise: bool, paper_run_id=None, sleep=None) -> int:  # noqa: ANN001, E501
    """Lock-guarded ingestion. A SECOND live instance acquires no lock and returns
    immediately WITHOUT any API call (single-instance safety). The lock is released
    on graceful shutdown; a crash auto-releases it (OS flock) so restart is safe.

    ``paper_run_id`` binds the poller to a specific P9 paper run: the FROZEN T0
    universe persisted for that run becomes the ONLY source of truth for the Crypto
    News tickers (and known-assets). If the run/universe cannot be resolved the
    poller FAILS CLOSED — it does NOT fall back to ``.env``/BTC-ETH and makes ZERO
    provider calls. Without a ``paper_run_id`` the standalone behavior (tickers from
    the configured MARKET_SYMBOLS) is preserved."""
    import time as _time

    # Bind to the frozen T0 universe FIRST — before any lock/adapter/poll — so a
    # resolution failure returns with zero API calls (fail-closed, no fallback).
    if paper_run_id is not None:
        from app.database import init_db, make_engine, make_session_factory
        from app.exceptions import PaperRunError
        from app.paper.build import _effective_settings
        from app.paper.universe_build import load_frozen_universe

        try:
            engine = make_engine(settings.database_url)
            init_db(engine)
            main_sf = make_session_factory(engine)
            symbols, universe_hash, _frozen_t0 = load_frozen_universe(main_sf, paper_run_id)
        except PaperRunError as exc:
            log.error(
                "frozen universe resolution FAILED for paper_run_id=%s: %s — fail-closed "
                "(no .env fallback, no API call)", paper_run_id, exc,
            )
            return 1
        settings = _effective_settings(settings, symbols)  # tickers = frozen universe
        log.info("news ingest bound to paper_run_id=%s universe_hash=%s symbols=%d",
                 paper_run_id, universe_hash[:16], len(symbols))

    sleep_fn = sleep or _time.sleep
    lock_path = f"{settings.news_ingest_db_path}.lock"
    lock = acquire_ingest_lock(lock_path)
    if lock is None:
        log.warning(
            "another news-ingest instance already holds %s; exiting (0 API calls)", lock_path
        )
        return 0

    try:
        cfg = settings.crypto_news_config()
        # Fail-closed: CryptoNewsApiAdapter raises if the token is empty (never invented).
        adapter = CryptoNewsApiAdapter(cfg)
        store = make_news_ingest_store(settings.news_ingest_db_path)
        interval = settings.crypto_news_poll_seconds
        log.info("news ingest start: db=%s interval=%ss items=%s tickers=%d supervise=%s "
                 "(token redacted)", settings.news_ingest_db_path, interval, cfg.items,
                 len(cfg.tickers), supervise)
        try:
            if supervise:
                _install_graceful_stop()
                while True:
                    poll_once(adapter, store)
                    sleep_fn(interval)
            else:
                for i in range(max(1, iterations)):
                    poll_once(adapter, store)
                    if i + 1 < max(1, iterations):
                        sleep_fn(interval)
        except KeyboardInterrupt:
            log.info("news ingest stop requested: shutting down gracefully")
    finally:
        release_ingest_lock(lock)  # release on normal shutdown; crash → OS releases

    log.info("news ingest done (no orders, no decisions)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Crypto News API ingestion poller (Phase 9).")
    parser.add_argument("--iterations", type=int, default=1, help="polls to run (finite mode)")
    parser.add_argument("--supervise", action="store_true", help="loop on the poll interval")
    parser.add_argument(
        "--paper-run-id", type=str, default=None,
        help="bind tickers to a P9 paper run's FROZEN T0 universe (fail-closed)",
    )
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings)
    return run(
        settings, iterations=args.iterations, supervise=args.supervise,
        paper_run_id=args.paper_run_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
