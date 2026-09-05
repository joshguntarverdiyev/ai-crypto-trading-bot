"""Portfolio/account domain state (Phase 6).

Authoritative runtime state (the DB is the source of truth; see
``app/portfolio/store.py``). Money is ``Decimal``. Exposure uses entry notional
(``quantity * average_entry``). Equity is mark-to-market where a mark is supplied,
falling back to cost (average_entry) when absent — deterministic and conservative;
live mark plumbing across symbols is deferred.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.market_data.models import Symbol
from app.strategy.models import SignalDirection


class PositionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True)
class Position:
    """Self-contained position (H10): risk params never need the Candidate."""

    symbol: Symbol
    direction: SignalDirection
    status: PositionStatus
    quantity: Decimal
    average_entry: Decimal
    stop_price: Decimal
    target_price: Decimal
    opened_at: datetime
    closed_at: datetime | None
    fees_paid: Decimal
    realized_pnl: Decimal
    strategy_version: str

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.average_entry


@dataclass(frozen=True)
class AccountState:
    """Reconstructable-from-DB working view of the account (H11)."""

    cash: Decimal
    open_positions: tuple[Position, ...]
    realized_pnl_cum: Decimal
    fees_paid_cum: Decimal
    hwm_equity: Decimal

    def position_for(self, symbol: Symbol) -> Position | None:
        key = str(symbol)
        for p in self.open_positions:
            if str(p.symbol) == key:
                return p
        return None

    def open_count(self) -> int:
        return len(self.open_positions)

    def exposure_by_symbol(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for p in self.open_positions:
            out[str(p.symbol)] = out.get(str(p.symbol), Decimal(0)) + p.notional
        return out

    def total_exposure(self) -> Decimal:
        return sum((p.notional for p in self.open_positions), Decimal(0))

    def group_exposure(self, group: frozenset[str]) -> Decimal:
        return sum(
            (p.notional for p in self.open_positions if p.symbol.base in group),
            Decimal(0),
        )

    def equity(self, marks: Mapping[str, Decimal] | None = None) -> Decimal:
        marks = marks or {}
        total = self.cash
        for p in self.open_positions:
            total += p.quantity * marks.get(str(p.symbol), p.average_entry)
        return total

    def unrealized_pnl(self, marks: Mapping[str, Decimal] | None = None) -> Decimal:
        marks = marks or {}
        total = Decimal(0)
        for p in self.open_positions:
            total += p.quantity * (marks.get(str(p.symbol), p.average_entry) - p.average_entry)
        return total
