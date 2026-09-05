"""Sizing result types (Phase 4).

A ``PositionPlan`` describes what a position *could* be if a trade were taken —
it is advisory, computed offline over caller-supplied state, holds no state, and
issues nothing. A ``SIZED`` result is NOT authorization to trade and NEVER
overrides the future P6 RiskManager (Contract clarification 2). Money is
``Decimal``; unknown/violated constraints → ``NO_TRADE`` (Master Plan §13).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.market_data.models import Symbol
from app.strategy.models import SignalDirection


class SizingDecision(StrEnum):
    SIZED = "sized"
    NO_TRADE = "no_trade"


class SizingReason(StrEnum):
    OK = "ok"
    NON_FINITE = "non_finite"  # non-finite candidate price → NO_TRADE
    INVALID_STOP = "invalid_stop"  # stop not strictly below a positive entry
    INSUFFICIENT_EQUITY = "insufficient_equity"  # equity <= 0
    RISK_BUDGET_ZERO = "risk_budget_zero"  # computed risk budget not positive
    BELOW_MIN_NOTIONAL = "below_min_notional"  # rounded size below min notional
    MAX_POSITIONS_REACHED = "max_positions_reached"
    EXCEEDS_SINGLE_ASSET_CAP = "exceeds_single_asset_cap"
    EXCEEDS_CORRELATED_CAP = "exceeds_correlated_cap"
    EXCEEDS_TOTAL_CAP = "exceeds_total_cap"
    LIQUIDITY_CAP = "liquidity_cap"  # conservative constant cap (no order book)


@dataclass(frozen=True)
class PositionPlan:
    """Advisory sized plan — not an order, not authorization to trade."""

    symbol: Symbol
    direction: SignalDirection
    entry_ref: Decimal  # tick-rounded
    stop_price: Decimal  # tick-rounded
    quantity: Decimal  # step-rounded (floored — never exceeds the risk budget)
    notional: Decimal  # quantity * entry_ref (quote)
    risk_amount: Decimal  # quantity * (entry_ref - stop_price) (quote)
    risk_per_trade_pct_effective: Decimal  # risk_amount / account_equity
    exposure_after_pct: Decimal  # total exposure incl. this plan / account_equity
    sizing_version: str
    config_version: str


@dataclass(frozen=True)
class SizingResult:
    decision: SizingDecision
    reason: SizingReason
    plan: PositionPlan | None
    sizing_version: str
    config_version: str
