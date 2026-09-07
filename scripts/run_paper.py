"""Run Phase 9 Paper Validation — an evolving paper account; NO real trading.

Offline-safe by default: with the default ``fixture`` sources this performs NO
network I/O and requires NO credentials. Real sources (public/keyless market data,
CryptoPanic news behind a conservative settle margin, Anthropic advisory analyst)
are enabled via configuration + the ``[shadow]`` extra; doing so still never
enables trading and never requires a trading key.

Runs ONLY when ``PAPER_VALIDATION_ENABLED=true`` AND ``LIVE_TRADING``/
``PAPER_TRADING`` are both false (enforced at startup). Each run uses its OWN
isolated SQLite database file under ``PAPER_RUNS_DIR``.

Usage::

    python -m scripts.run_paper                 # one boundary sweep (new run), then exit
    python -m scripts.run_paper --iterations 3  # three sweeps (sleeps between)
    python -m scripts.run_paper --run-id <id>   # resume an existing run by id
    python -m scripts.run_paper --run-id <id> --supervise   # long-lived, boundary-aligned

``--supervise`` runs the self-scheduling boundary loop (``PaperRunner.run``) for a
long-running, restart-safe deployment (e.g. under launchd ``KeepAlive``). It sleeps
until each completed primary-timeframe boundary and never advances past real time.
On ``SIGTERM``/``SIGINT`` (launchd stop / Ctrl-C) it stops the loop gracefully and
releases ownership so the next start resumes instantly; a hard crash / ``SIGKILL``
leaves the run resumable via the stale-heartbeat takeover + released OS lock. In
every mode decisions are idempotent per ``(decision_time, symbol)`` and fills are
guarded by ``intent_id`` — a restart never creates a duplicate decision or fill.

This process can never place a real order.
"""

from __future__ import annotations

import argparse
import logging
import signal

from app.config import load_settings
from app.database import init_db, make_engine, make_session_factory
from app.logging_config import configure_logging
from app.paper.build import build_paper_system
from app.paper.store import close_paper_run
from app.time_utils import utc_now

log = logging.getLogger("scripts.run_paper")


def _install_graceful_stop() -> None:
    """Translate SIGTERM (launchd stop) into KeyboardInterrupt so the ``finally``
    cleanly closes the run (releases ownership). SIGINT already raises it."""

    def _handler(signum, _frame):  # noqa: ANN001, ANN202
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGTERM, _handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 9 Paper Validation (simulated).")
    parser.add_argument("--iterations", type=int, default=1, help="boundary sweeps to run")
    parser.add_argument("--run-id", type=str, default=None, help="resume an existing run")
    parser.add_argument(
        "--supervise", action="store_true",
        help="run the self-scheduling boundary loop until stopped (launchd/tmux)",
    )
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings)

    # Main (catalog) database.
    engine = make_engine(settings.database_url)
    init_db(engine)
    main_sf = make_session_factory(engine)

    cfg = settings.paper_validation_config()
    log.info(
        "paper start: source=%s news=%s ai=%s symbols=%s supervise=%s "
        "live_trading=%s paper_trading=%s paper_validation_enabled=%s",
        cfg.market_data_source.value, cfg.news_source.value, cfg.ai_provider.value,
        [str(s) for s in cfg.symbols], args.supervise, settings.live_trading,
        settings.paper_trading, settings.paper_validation_enabled,
    )

    runner, run_id = build_paper_system(settings, main_sf, run_id=args.run_id)
    log.info("paper run_id=%s db=%s/%s.db", run_id, cfg.paper_runs_dir, run_id)
    try:
        if args.supervise:
            _install_graceful_stop()
            log.info("paper supervise: boundary loop started (stop with SIGTERM/SIGINT)")
            runner.run()  # blocks; boundary-aligned until interrupted
        else:
            for _ in range(max(1, args.iterations)):
                results = runner.run_once(utc_now())
                for r in results:
                    log.info("paper decision: %s -> %s (%s)", r.symbol, r.outcome.value, r.reason)
    except KeyboardInterrupt:
        log.info("paper stop requested: shutting down run_id=%s gracefully", run_id)
    finally:
        close_paper_run(main_sf, run_id, status="stopped")

    log.info("paper done: run_id=%s (simulated; no real orders placed)", run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
