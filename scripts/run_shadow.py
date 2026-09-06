"""Run Shadow Mode (Phase 8) — real-time decision pipeline, ZERO execution.

Offline-safe by default: with the default ``fixture`` sources this performs NO
network I/O, requires NO credentials, and writes only shadow-audit rows (no
operational/portfolio state). Enable real sources (public/keyless market data,
CryptoPanic news, Anthropic analyst) via configuration + the ``[shadow]`` extra;
doing so still never enables trading and never requires a trading key.

Usage::

    python -m scripts.run_shadow                 # one boundary sweep, then exit
    python -m scripts.run_shadow --iterations 3  # three sweeps (sleeps between)

This process can never place a trade.
"""

from __future__ import annotations

import argparse
import logging

from app.config import load_settings
from app.database import init_db, make_engine, make_session_factory
from app.logging_config import configure_logging
from app.shadow.build import build_shadow_system
from app.shadow.store import close_shadow_run
from app.time_utils import utc_now

log = logging.getLogger("scripts.run_shadow")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Shadow Mode (no execution).")
    parser.add_argument("--iterations", type=int, default=1, help="boundary sweeps to run")
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings)

    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    cfg = settings.shadow_config()
    log.info(
        "shadow start: source=%s news=%s ai=%s symbols=%s live_trading=%s paper_trading=%s",
        cfg.market_data_source.value, cfg.news_source.value, cfg.ai_provider.value,
        [str(s) for s in cfg.symbols], settings.live_trading, settings.paper_trading,
    )

    runner, run_id = build_shadow_system(settings, session_factory)
    try:
        results = runner.run_once(utc_now())
        for r in results:
            log.info("shadow decision: %s/%s -> %s (%s)", r.symbol, r.decision_time.isoformat(),
                     r.outcome.value, r.reason)
        for _ in range(max(0, args.iterations - 1)):
            runner.run_once(utc_now())
    finally:
        close_shadow_run(session_factory, run_id, status="stopped")

    log.info("shadow done: run_id=%s (no orders placed; no portfolio state changed)", run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
