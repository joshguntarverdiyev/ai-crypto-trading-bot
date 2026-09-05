"""Persisted paper orders + fills (Phase 6).

``paper_orders.intent_id`` is a client-generated idempotency key with a UNIQUE
constraint — re-processing the same intent can never create a duplicate order or
fill (Master Plan §18). ``paper_fills`` is append-only.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import PreciseDecimal


class PaperOrderRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "paper_orders"
    __table_args__ = (
        UniqueConstraint("intent_id", name="uq_paper_orders_intent"),
        Index("ix_paper_orders_symbol_state", "symbol", "state"),
    )

    intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperFillRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "paper_fills"
    __table_args__ = (Index("ix_paper_fills_order", "order_id"),)

    order_id: Mapped[str] = mapped_column(
        ForeignKey("paper_orders.id"), nullable=False
    )
    fill_qty: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    fee: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    is_partial: Mapped[bool] = mapped_column(nullable=False)
