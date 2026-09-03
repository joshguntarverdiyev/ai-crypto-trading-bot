"""Bootstrap: runs cleanly offline and initializes the database."""

from __future__ import annotations

from sqlalchemy import inspect

from app.database import make_engine
from app.main import bootstrap


def test_bootstrap_returns_zero_and_creates_db(test_settings) -> None:
    # The _no_network fixture guarantees this exercises no external services.
    rc = bootstrap(test_settings)
    assert rc == 0

    engine = make_engine(test_settings.database_url)
    tables = set(inspect(engine).get_table_names())
    assert {"system_events", "errors", "config_versions"} <= tables
