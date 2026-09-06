"""Persisted Shadow Mode audit (Phase 8) — shadow-only, NOT operational.

Two tables, separate from the operational P6 tables (positions/portfolio_snapshots
/paper_orders/paper_fills): the shadow engine writes **no** operational state.

* ``shadow_decisions`` — one row per processed eligible boundary ``(decision_time,
  symbol)`` (**unique** → idempotency / no duplicate durable decisions). Records
  the shadow outcome, stage/reason, links to the shared ``claude_decisions`` /
  ``risk_decisions`` audit rows, a market + feature/regime summary, and — on a
  would-be trade — the HYPOTHETICAL order and (non-executed) fill.
* ``shadow_runs`` — the Phase 8 run index (distinct from P9's ``paper_trading_runs``):
  source selection, version tags, and a secret-free config snapshot.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ShadowDecisionRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "shadow_decisions"
    __table_args__ = (
        UniqueConstraint("decision_time", "symbol", name="uq_shadow_decision_identity"),
        Index("ix_shadow_decisions_dt", "decision_time", "symbol"),
    )

    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    shadow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Shadow outcome (NOT an execution): hold | reject | would_trade.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)

    # Links to the shared audit rows (§16 reconstruction chain).
    claude_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    risk_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Market + feature/regime summary (denormalized; avoids high-volume tables, §15).
    regime: Mapped[str | None] = mapped_column(String(24), nullable=True)
    market_summary: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    features_summary: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON

    # HYPOTHETICAL would-be order + (non-executed) fill — set only on would_trade.
    hyp_side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    hyp_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    hyp_entry_ref: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    hyp_stop_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    hyp_target_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    hyp_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    hyp_fill_fee: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    hyp_fill_state: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Version tags (§16 reconstructability).
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_set_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class ShadowRunRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "shadow_runs"

    run_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")

    symbols: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    timeframes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    market_data_source: Mapped[str] = mapped_column(String(24), nullable=False)
    market_data_exchange_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    news_source: Mapped[str] = mapped_column(String(24), nullable=False)
    ai_provider: Mapped[str] = mapped_column(String(24), nullable=False)

    # Version tags.
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_set_version: Mapped[str] = mapped_column(String(64), nullable=False)
    cost_model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    sizing_version: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_version: Mapped[str] = mapped_column(String(128), nullable=False)
    ai_analyst_version: Mapped[str] = mapped_column(String(64), nullable=False)

    config_snapshot: Mapped[str] = mapped_column(Text, nullable=False)  # JSON (secret-free)
