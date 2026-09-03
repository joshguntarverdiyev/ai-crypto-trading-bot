"""Foundation models: UUID ids and UTC-aware timestamps."""

from __future__ import annotations

from datetime import timedelta

from app.database import session_scope
from app.models import ConfigVersion, SystemEvent
from app.time_utils import ensure_utc


def test_uuid_and_utc_timestamp_on_persist(db) -> None:
    _engine, sf, _url = db
    with session_scope(sf) as s:
        event = SystemEvent(level="INFO", component="c", message="m")
        s.add(event)
        s.flush()  # apply column defaults

        assert isinstance(event.id, str)
        assert len(event.id) == 36  # UUID4 string
        assert event.created_at is not None
        assert ensure_utc(event.created_at).utcoffset() == timedelta(0)


def test_version_default(db) -> None:
    _engine, sf, _url = db
    with session_scope(sf) as s:
        cv = ConfigVersion(name="app", config_hash="abc", snapshot="{}")
        s.add(cv)
        s.flush()
        assert cv.version == 1
