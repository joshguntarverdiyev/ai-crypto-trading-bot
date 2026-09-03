"""Configuration version audit model (Phase 0 foundation).

Establishes the *versioning direction* required by the Master Plan (§16): the
system must be able to record which configuration was in effect for any past
decision. Strategy/model/prompt versioning follow the same pattern in later
phases (documented in docs/architecture.md), and are NOT implemented here.
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin, VersionMixin


class ConfigVersion(Base, UUIDMixin, TimestampMixin, VersionMixin):
    """An immutable snapshot of a named configuration at a point in time."""

    __tablename__ = "config_versions"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)
