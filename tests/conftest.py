"""Shared test fixtures. Tests are deterministic and offline."""

from __future__ import annotations

import socket

import pytest

from app.config import Settings, load_settings
from app.database import init_db, make_engine, make_session_factory


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block all outbound network access for the duration of every test."""

    def blocked(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("Network access is not allowed in tests (offline guarantee).")

    monkeypatch.setattr(socket, "create_connection", blocked, raising=True)
    monkeypatch.setattr(socket, "getaddrinfo", blocked, raising=True)


@pytest.fixture
def db(tmp_path):
    """A fresh, file-backed SQLite database with foundation tables created."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_engine(url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    return engine, session_factory, url


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    """Isolated settings (no on-disk .env) pointing at a temp database."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    return load_settings(_env_file=None, environment="test", database_url=url)
