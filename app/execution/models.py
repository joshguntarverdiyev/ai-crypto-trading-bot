"""Paper execution types + order state machine (Phase 6).

State machine (Master Plan §18): INTENDED → SUBMITTING → SUBMITTED →
{FILLED | PARTIAL | REJECTED | CANCELED | UNKNOWN}. In paper the SUBMITTING/
SUBMITTED steps are immediate but modeled for parity. Simulated only — never a
real order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.market_data.models import Symbol


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"  # entry
    STOP = "stop"  # bot-managed stop exit (no exchange-native stop, P6)
    TARGET = "target"  # target exit


class OrderState(StrEnum):
    INTENDED = "intended"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class ExecReason(StrEnum):
    OK = "ok"
    PARTIAL = "partial"  # partial fill to the liquidity cap (H7)
    BELOW_MIN_NOTIONAL = "below_min_notional"
    INVALID_QTY = "invalid_qty"
    DUPLICATE = "duplicate"  # idempotent reuse of an existing terminal order


@dataclass(frozen=True)
class Intent:
    """A client-generated execution intent. ``intent_id`` is the idempotency key."""

    intent_id: str
    symbol: Symbol
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    reference_price: Decimal
    decision_time: datetime


@dataclass(frozen=True)
class PaperFill:
    fill_qty: Decimal
    fill_price: Decimal
    fee: Decimal
    is_partial: bool


@dataclass(frozen=True)
class ExecutionResult:
    state: OrderState
    reason: ExecReason
    intent: Intent
    fills: tuple[PaperFill, ...]
    reused: bool  # True when an existing terminal order was returned (idempotent)

    @property
    def filled_qty(self) -> Decimal:
        return sum((f.fill_qty for f in self.fills), Decimal(0))

    @property
    def total_fee(self) -> Decimal:
        return sum((f.fee for f in self.fills), Decimal(0))
