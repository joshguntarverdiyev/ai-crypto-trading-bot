"""Backtest result + manifest types (Phase 7).

Descriptive, deterministic outputs of the pure-quant replay. Money is ``Decimal``;
ratios are floats. Nothing here is an order or authorization to trade — a backtest
is offline research and makes no edge/performance claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.exceptions import AppError


class BacktestError(AppError):
    """Base class for backtest tooling errors."""


class BacktestDataError(BacktestError):
    """The historical dataset is missing, malformed, gapped, or invalid (fail-closed)."""


@dataclass(frozen=True)
class BacktestTrade:
    """One completed round-trip (entry → stop/target exit)."""

    symbol: str
    direction: str
    entry_time: datetime
    entry_price: Decimal
    quantity: Decimal
    entry_fee: Decimal
    exit_time: datetime
    exit_price: Decimal
    exit_fee: Decimal
    exit_reason: str  # "stop" | "target"
    gross_pnl: Decimal  # quantity * (exit_price - entry_price)
    net_pnl: Decimal  # gross_pnl - entry_fee - exit_fee (equity-consistent)
    bars_held: int

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0


@dataclass(frozen=True)
class EquityPoint:
    time: datetime
    equity: Decimal
    cash: Decimal
    open_positions: int


@dataclass(frozen=True)
class BacktestEvent:
    """A notable non-trade event (HOLD/REJECT/HALT/PAUSE) for audit/reporting."""

    time: datetime
    kind: str
    symbol: str | None
    detail: str


@dataclass(frozen=True)
class RunManifest:
    """Everything needed to reproduce a run bit-for-bit (§16 / §22)."""

    dataset_name: str
    dataset_hash: str
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    range_start: datetime | None
    range_end: datetime | None
    seed: int
    cost_scenario: str
    entry_fill_rule: str
    halt_policy: str
    engine_version: str
    indicator_set_version: str
    cost_model_version: str
    strategy_version: str
    sizing_version: str
    risk_version: str
    paper_version: str
    config_snapshot: dict[str, str]
    run_time: datetime


@dataclass(frozen=True)
class BacktestResult:
    manifest: RunManifest
    starting_equity: Decimal
    ending_equity: Decimal
    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint]
    events: list[BacktestEvent] = field(default_factory=list)
    final_kill_status: str = "running"

    @property
    def net_pnls(self) -> list[Decimal]:
        return [t.net_pnl for t in self.trades]
