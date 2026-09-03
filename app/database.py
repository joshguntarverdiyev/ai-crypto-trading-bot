"""Database foundation (Phase 0).

SQLAlchemy 2.x engine, session factory, initialization, and a transaction
scope with correct commit/rollback semantics. SQLite is used for development
and tests; the layer is written to remain compatible with a later
SQLite -> PostgreSQL transition.

This layer knows nothing about exchanges, trading, or any domain behavior.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.exceptions import DatabaseError
from app.models.base import Base

_SQLITE_FILE_PREFIX = "sqlite:///"


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """Create the parent directory for a file-based SQLite database, if needed."""
    if not database_url.startswith(_SQLITE_FILE_PREFIX):
        return
    raw_path = database_url[len(_SQLITE_FILE_PREFIX):]
    if not raw_path or raw_path == ":memory:":
        return
    parent = Path(raw_path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


def make_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine for the given URL."""
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        _ensure_sqlite_parent_dir(database_url)
    return create_engine(database_url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create all foundation tables. Imports models so metadata is registered."""
    import app.models  # noqa: F401  (registers ORM models on Base.metadata)

    try:
        Base.metadata.create_all(engine)
    except Exception as exc:  # pragma: no cover - defensive
        raise DatabaseError(f"Failed to initialize database: {exc}") from exc


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on exception, always close."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
