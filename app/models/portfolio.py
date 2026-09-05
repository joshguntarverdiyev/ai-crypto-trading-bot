"""Persisted positions + portfolio snapshots (Phase 6).

Positions are self-contained (H10): all state needed for restart, risk, and exits
is stored, so an open position never depends on reconstructing a Candidate.
Snapshots persist cash/equity/PnL/fees and the drawdown high-water mark so
daily/weekly baselines and HWM survive restart (H4/H5).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import PreciseDecimal


class PositionRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "positions"
    # One OPEN position per symbol is enforced in the repository (dialect-safe).
    __table_args__ = (Index("ix_positions_symbol_status", "symbol", "status"),)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    average_entry: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    stop_price: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    target_price: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fees_paid: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortfolioSnapshotRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (Index("ix_portfolio_snapshots_time", "snapshot_time"),)

    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    equity: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    total_exposure: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    realized_pnl_cum: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    fees_paid_cum: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    hwm_equity: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    open_positions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
