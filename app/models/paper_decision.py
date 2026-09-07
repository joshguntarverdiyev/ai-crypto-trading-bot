"""Persisted Phase 9 per-boundary paper-validation audit — ``paper_decisions``.

Lives INSIDE each run's own database file (per-run database isolation, "D-ISO";
final P9 plan §35.1/§26). One row per processed boundary ``(decision_time,
symbol)`` (**unique** → idempotency accelerator + gap detector + Shadow↔Paper
comparison substrate). It links to the same-DB shared audit rows
(``claude_decisions``/``risk_decisions``) and to any realized order (``intent_id``).

``paper_run_id`` is a **NOT-NULL immutable run-identity field** that MUST equal the
run DB's identity (``paper_trading_runs.id``). It is **NOT a cross-database foreign
key** — SQLite cannot FK across files, and none is declared; the invariant is
enforced in the application (app/paper/store.py + recorder). Cross-run uniqueness
is unnecessary: the database file itself is the isolation boundary.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import PreciseDecimal


class PaperDecisionRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "paper_decisions"
    __table_args__ = (
        UniqueConstraint("decision_time", "symbol", name="uq_paper_decision_identity"),
        Index("ix_paper_decisions_dt", "decision_time", "symbol"),
    )

    # Immutable run identity == this run DB's identity (NOT a cross-DB FK).
    paper_run_id: Mapped[str] = mapped_column(String(36), nullable=False)

    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)

    # Boundary outcome (see app/paper/models.py::PaperOutcome).
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)

    # Same-DB links (§16 reconstruction chain).
    claude_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    risk_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    regime: Mapped[str | None] = mapped_column(String(24), nullable=True)
    market_summary: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    features_summary: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON

    # Post-boundary portfolio snapshot references (derived; authoritative curve is
    # the consolidated portfolio_snapshots series).
    equity_after: Mapped[Decimal | None] = mapped_column(PreciseDecimal, nullable=True)
    exposure_after_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Version tags (§16 reconstructability).
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_set_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
