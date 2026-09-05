"""Persisted news item (Phase 6). Idempotent identity ``(source, dedup_key)``."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class NewsRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "news"
    __table_args__ = (
        UniqueConstraint("source", "dedup_key", name="uq_news_identity"),
        Index("ix_news_available_at", "available_at"),
    )

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    availability_known: Mapped[bool] = mapped_column(Boolean, nullable=False)
    affected_assets: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # json
    trust: Mapped[float] = mapped_column(Float, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    news_pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
