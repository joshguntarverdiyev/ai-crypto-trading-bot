"""Phase 9 (redesign) universe snapshot + per-boundary funnel counters.

Both live in the RUN's OWN database (per-run isolation, D-ISO) — additive audit
tables that do NOT alter any frozen P6 operational schema. ``paper_universe``
records the reproducible T0 selection (symbol, rank, volume, hash) for
pre-registration/audit; ``paper_boundary_funnel`` records deterministic funnel
counters per decision boundary for observability + Claude-budget accounting.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import PreciseDecimal


class PaperUniverseRecord(Base, UUIDMixin, TimestampMixin):
    """One selected universe symbol at T0 (fixed for the validation window)."""

    __tablename__ = "paper_universe"
    __table_args__ = (UniqueConstraint("selection_hash", "symbol", name="uq_universe_symbol"),)

    paper_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    selection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = highest 24h volume
    quote_volume_24h: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperBoundaryFunnelRecord(Base, UUIDMixin, TimestampMixin):
    """Deterministic per-boundary funnel counters (observability + Claude budget)."""

    __tablename__ = "paper_boundary_funnel"
    __table_args__ = (
        UniqueConstraint("paper_run_id", "decision_time", name="uq_funnel_boundary"),
    )

    paper_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    universe_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claude_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claude_budget_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_rejects: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
