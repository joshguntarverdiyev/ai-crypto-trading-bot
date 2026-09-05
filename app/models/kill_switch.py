"""Persisted kill-switch state (Phase 6).

A single-row table: the kill-switch status survives restart (a HALT is never lost,
H9). Written in an independent session from the per-tick trading transaction.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

KILL_SWITCH_ROW_ID = "singleton"


class KillSwitchRecord(Base, TimestampMixin):
    __tablename__ = "kill_switch_state"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=KILL_SWITCH_ROW_ID)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tripped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
