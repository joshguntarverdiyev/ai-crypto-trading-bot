"""Persisted candle model (Phase 1).

``CandleRecord`` is the ORM row for the ``candles`` table. It is distinct from
the domain :class:`app.market_data.models.Candle`; the repository maps between
them. Persistence identity is ``(source, symbol, timeframe, open_time)`` so two
data sources can never overwrite each other's candles.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import PreciseDecimal


class CandleRecord(Base, UUIDMixin, TimestampMixin):
    """A persisted, closed, validated OHLCV candle."""

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "source", "symbol", "timeframe", "open_time", name="uq_candles_identity"
        ),
    )

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    open: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    high: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    low: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    close: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)
    volume: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)

    source_meta: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # ingested_at is provided by TimestampMixin.created_at (UTC).
