"""ORM base and mixins (Phase 0 foundation).

Conventions that all future audit models must follow:

* ``UUIDMixin``     — canonical UUID4 string primary key.
* ``TimestampMixin``— timezone-aware UTC ``created_at`` (Master Plan §18.1).
* ``VersionMixin``  — integer ``version`` for audit-critical, versioned records.

These conventions keep the audit trail reconstructable (Master Plan §16) and
let later phases extend the schema without a rewrite.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.ids import new_id
from app.time_utils import utc_now


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class UUIDMixin:
    """Canonical UUID4 string primary key."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampMixin:
    """Timezone-aware UTC creation timestamp."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class VersionMixin:
    """Integer version for audit-critical, versioned records."""

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
