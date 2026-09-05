"""Persisted analyst + risk decisions (Phase 6).

``claude_decisions`` denormalizes the exact runtime model_id/model_class/
prompt_version/ai_analyst_version (Master Plan §16 — non-reproducible output must
be auditable). ``risk_decisions`` records the RiskManager's binding outcome.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ClaudeDecisionRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "claude_decisions"
    __table_args__ = (Index("ix_claude_decisions_dt", "decision_time", "symbol"),)

    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_codes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    affected_assets: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    event_risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    failure: Mapped[str] = mapped_column(String(32), nullable=False)
    # Denormalized audit identity (§16):
    model_class: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ai_analyst_version: Mapped[str] = mapped_column(String(32), nullable=False)
    news_pipeline_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_seconds: Mapped[float] = mapped_column(Float, nullable=False)


class RiskDecisionRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "risk_decisions"
    __table_args__ = (Index("ix_risk_decisions_dt", "decision_time", "symbol"),)

    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    reason_codes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recomputed_risk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    exposure_after_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluated: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    claude_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    risk_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_version: Mapped[str] = mapped_column(String(255), nullable=False)
