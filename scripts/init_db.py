"""Initialize the local database from the current configuration (Phase 0).

Offline-only: creates the foundation tables. Does not connect to any exchange
or external service. Run with the project virtualenv active:

    python -m scripts.init_db
"""

from __future__ import annotations

from app.config import load_settings
from app.database import init_db, make_engine
from app.logging_config import configure_logging
from app.models.base import Base


def main() -> None:
    settings = load_settings()
    configure_logging(settings)
    engine = make_engine(settings.database_url)
    init_db(engine)
    print(f"Initialized database at: {settings.database_url}")
    print(f"Tables: {sorted(Base.metadata.tables.keys())}")


if __name__ == "__main__":
    main()
