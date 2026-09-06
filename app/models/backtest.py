"""Persisted backtest run index (Phase 7 — research artifacts, NOT operational).

A ``backtest_runs`` row is the audit/index entry for one deterministic backtest
run (Master Plan §16). It records the dataset content hash, the seed, every
version tag, a secret-free config snapshot, and a summary-metrics JSON, plus the
filesystem path to the full artifacts. It is **separate** from operational
tables (positions/portfolio_snapshots/paper_orders/...): the backtester never
writes operational state. The dashboard reads this table for its run index only.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class BacktestRunRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "backtest_runs"

    run_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    symbols: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    timeframes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    range_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    range_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seed: Mapped[int] = mapped_column(nullable=False)
    cost_scenario: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_fill_rule: Mapped[str] = mapped_column(String(16), nullable=False)
    halt_policy: Mapped[str] = mapped_column(String(24), nullable=False)
    # Version tags (§16 reconstructability).
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_set_version: Mapped[str] = mapped_column(String(64), nullable=False)
    cost_model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    sizing_version: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_version: Mapped[str] = mapped_column(String(128), nullable=False)
    paper_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # Snapshots + artifacts.
    config_snapshot: Mapped[str] = mapped_column(Text, nullable=False)  # JSON (secret-free)
    summary_metrics: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
