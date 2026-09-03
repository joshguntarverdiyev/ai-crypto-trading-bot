"""Identifier strategy (Phase 0 foundation).

Canonical internal IDs are UUID4 strings: unique, stable, and safe for
database relationships and immutable audit records.

NOTE (future phases): external/exchange identifiers and idempotency keys
(e.g. ``clientOrderId`` for duplicate-order protection — Master Plan §18) are
NOT implemented in Phase 0. When execution is built, external IDs must be
stored alongside — never conflated with — these internal IDs.
"""

from __future__ import annotations

import uuid


def new_id() -> str:
    """Return a new canonical internal identifier (UUID4 string)."""
    return str(uuid.uuid4())
