"""System event audit model (Phase 0 foundation)."""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class SystemEvent(Base, UUIDMixin, TimestampMixin):
    """A record of a notable system-level event (infrastructure, lifecycle)."""

    __tablename__ = "system_events"

    level: Mapped[str] = mapped_column(String(16), nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
