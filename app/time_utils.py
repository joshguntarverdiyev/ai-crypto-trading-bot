"""Time policy and utilities (Phase 0 foundation).

Project-wide time policy (Master Plan §18.1):

* **UTC is canonical.** All persisted timestamps are timezone-aware UTC.
* Timezone conversion happens ONLY at the presentation/reporting layer.
* A monotonic clock is used for measuring local durations/latency, never for
  wall-clock timestamps.

Exchange clock synchronization / drift detection is a LATER phase and is not
implemented here.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, tzinfo


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Normalize a ``datetime`` to timezone-aware UTC.

    A naive ``datetime`` is assumed to already represent UTC and is tagged as
    such; an aware ``datetime`` is converted to UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_display(dt: datetime, tz: tzinfo) -> datetime:
    """Convert a ``datetime`` to a display timezone (presentation layer only)."""
    return ensure_utc(dt).astimezone(tz)


def monotonic() -> float:
    """Monotonic clock reading (seconds) for measuring local durations/latency."""
    return time.monotonic()
