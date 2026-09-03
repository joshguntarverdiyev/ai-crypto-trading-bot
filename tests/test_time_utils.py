"""UTC time policy and helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.time_utils import ensure_utc, monotonic, to_display, utc_now


def test_utc_now_is_aware_utc() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_ensure_utc_tags_naive_as_utc() -> None:
    naive = datetime(2026, 1, 1, 12, 0, 0)
    out = ensure_utc(naive)
    assert out.tzinfo is UTC
    assert out.hour == 12


def test_ensure_utc_converts_aware() -> None:
    plus2 = timezone(timedelta(hours=2))
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus2)
    out = ensure_utc(aware)
    assert out.utcoffset() == timedelta(0)
    assert out.hour == 10  # 12:00+02:00 -> 10:00 UTC


def test_to_display_is_presentation_only() -> None:
    plus3 = timezone(timedelta(hours=3))
    out = to_display(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC), plus3)
    assert out.hour == 12
    assert out.utcoffset() == timedelta(hours=3)


def test_monotonic_is_non_decreasing() -> None:
    a = monotonic()
    b = monotonic()
    assert isinstance(a, float)
    assert b >= a
