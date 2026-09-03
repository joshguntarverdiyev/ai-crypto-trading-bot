"""Offline application bootstrap (Phase 0).

The bootstrap:
  1. loads configuration,
  2. initializes logging,
  3. initializes the database,
  4. performs basic startup validation,
  5. exits cleanly.

It performs NO network I/O and does NOT connect to any exchange, call any AI
model, or start any trading engine. It is safe to run on a fully offline
machine.
"""

from __future__ import annotations

import logging

from app.config import Settings, load_settings
from app.database import init_db, make_engine
from app.exceptions import ConfigError
from app.logging_config import configure_logging

log = logging.getLogger("app.main")


def startup_validation(settings: Settings) -> None:
    """Fail-closed Phase 0 safety checks."""
    # Defense in depth: config already forbids this, re-assert here.
    if settings.live_trading:
        msg = "Refusing to start: live_trading is enabled but no execution layer exists."
        raise ConfigError(msg)


def bootstrap(settings: Settings | None = None) -> int:
    """Run the offline startup sequence. Returns a process exit code."""
    settings = settings or load_settings()
    configure_logging(settings)
    log.info(
        "startup: environment=%s app=%s live_trading=%s",
        settings.environment.value,
        settings.app_name,
        settings.live_trading,
    )

    engine = make_engine(settings.database_url)
    init_db(engine)
    startup_validation(settings)

    log.info("ready: Phase 0 foundation (no exchange, no AI, no trading)")
    return 0


def main() -> None:
    raise SystemExit(bootstrap())


if __name__ == "__main__":
    main()
