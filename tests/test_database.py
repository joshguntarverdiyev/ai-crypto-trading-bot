"""Database: initialization, CRUD, and transaction rollback."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select

from app.database import session_scope
from app.models import SystemEvent


def test_init_creates_foundation_tables(db) -> None:
    engine, _sf, _url = db
    tables = set(inspect(engine).get_table_names())
    assert {"system_events", "errors", "config_versions"} <= tables


def test_crud_roundtrip(db) -> None:
    _engine, sf, _url = db
    with session_scope(sf) as s:
        s.add(SystemEvent(level="INFO", component="test", message="hello"))

    with session_scope(sf) as s:
        rows = s.scalars(select(SystemEvent)).all()
        assert len(rows) == 1
        assert rows[0].component == "test"
        assert rows[0].message == "hello"


def test_rollback_on_exception(db) -> None:
    _engine, sf, _url = db
    with pytest.raises(RuntimeError):
        with session_scope(sf) as s:
            s.add(SystemEvent(level="ERROR", component="test", message="boom"))
            raise RuntimeError("force rollback")

    with session_scope(sf) as s:
        assert s.scalars(select(SystemEvent)).all() == []
