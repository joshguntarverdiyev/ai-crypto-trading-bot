"""Error audit model (Phase 0 foundation)."""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ErrorRecord(Base, UUIDMixin, TimestampMixin):
    """A persisted record of a handled error, for later inspection/audit."""

    __tablename__ = "errors"

    error_type: Mapped[str] = mapped_column(String(64), nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
