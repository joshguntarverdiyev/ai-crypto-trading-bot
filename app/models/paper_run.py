"""Persisted Phase 9 paper-validation run catalog — ``paper_trading_runs``.

This is the ONLY P9 table that lives in the MAIN (``DATABASE_URL``) database. It is
a **catalog / ownership / lifecycle registry** and holds **no operational portfolio
state** — that lives in each run's own dedicated SQLite database file (per-run
database isolation, "D-ISO"; final P9 plan §35.1/§26). The primary key ``id`` IS
the immutable run identity ("run_id") and equals the run DB's identity; there is
**no cross-database foreign key** to the run DB (SQLite cannot FK across files).

A run's operational data (``paper_orders``/``paper_fills``/``positions``/
``portfolio_snapshots``/``paper_decisions`` + shared audit + kill state) is
isolated in ``{paper_runs_dir}/{id}.db`` — so different runs have physically
separate intent namespaces and can never contaminate one another.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import PreciseDecimal


class PaperTradingRunRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "paper_trading_runs"

    # ``id`` (UUIDMixin PK) IS the immutable run identity used as the run DB name.
    db_path: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")

    # Single-writer ownership (catalog-serialized; see app/paper/store.py).
    owner_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    symbols: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    timeframes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    market_data_source: Mapped[str] = mapped_column(String(24), nullable=False)
    market_data_exchange_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    news_source: Mapped[str] = mapped_column(String(24), nullable=False)
    ai_provider: Mapped[str] = mapped_column(String(24), nullable=False)

    starting_equity: Mapped[Decimal] = mapped_column(PreciseDecimal, nullable=False)

    # Version tags (§16 reconstructability).
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_set_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    cost_model_version: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    sizing_version: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    risk_version: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    ai_analyst_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # Pre-registration digest (locked before results are read; §35.4). Nullable
    # until pre-registration is recorded for the run.
    prereg_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)

    config_snapshot: Mapped[str] = mapped_column(Text, nullable=False)  # JSON (secret-free)
