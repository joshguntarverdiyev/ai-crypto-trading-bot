"""Pure paper-accounting ledger (Phase 6, H12).

Deterministic functions over an immutable ``AccountState`` → new state + the
affected ``Position``. No double-counting: entry and exit fees are each booked
once; realized PnL flows only on exit; unrealized/equity use marks (see
``AccountState``). All money is ``Decimal``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.market_data.models import Symbol
from app.portfolio.models import AccountState, Position, PositionStatus
from app.strategy.models import SignalDirection


def _without(positions: tuple[Position, ...], symbol: Symbol) -> tuple[Position, ...]:
    key = str(symbol)
    return tuple(p for p in positions if str(p.symbol) != key)


def apply_entry(
    account: AccountState,
    *,
    symbol: Symbol,
    direction: SignalDirection,
    fill_qty: Decimal,
    fill_price: Decimal,
    fee: Decimal,
    stop_price: Decimal,
    target_price: Decimal,
    strategy_version: str,
    at: datetime,
) -> tuple[AccountState, Position]:
    existing = account.position_for(symbol)
    if existing is None:
        position = Position(
            symbol=symbol, direction=direction, status=PositionStatus.OPEN,
            quantity=fill_qty, average_entry=fill_price, stop_price=stop_price,
            target_price=target_price, opened_at=at, closed_at=None,
            fees_paid=fee, realized_pnl=Decimal(0), strategy_version=strategy_version,
        )
    else:
        new_qty = existing.quantity + fill_qty
        new_avg = (
            existing.quantity * existing.average_entry + fill_qty * fill_price
        ) / new_qty
        position = Position(
            symbol=symbol, direction=existing.direction, status=PositionStatus.OPEN,
            quantity=new_qty, average_entry=new_avg, stop_price=stop_price,
            target_price=target_price, opened_at=existing.opened_at, closed_at=None,
            fees_paid=existing.fees_paid + fee, realized_pnl=existing.realized_pnl,
            strategy_version=existing.strategy_version,
        )
    new_positions = (*_without(account.open_positions, symbol), position)
    new_account = AccountState(
        cash=account.cash - fill_qty * fill_price - fee,
        open_positions=new_positions,
        realized_pnl_cum=account.realized_pnl_cum,
        fees_paid_cum=account.fees_paid_cum + fee,
        hwm_equity=account.hwm_equity,
    )
    return new_account, position


def apply_exit(
    account: AccountState,
    *,
    symbol: Symbol,
    exit_qty: Decimal,
    fill_price: Decimal,
    fee: Decimal,
    at: datetime,
) -> tuple[AccountState, Position]:
    existing = account.position_for(symbol)
    if existing is None:
        raise ValueError(f"no open position to exit for {symbol}")
    realized_delta = exit_qty * (fill_price - existing.average_entry) - fee
    remaining = existing.quantity - exit_qty
    closed = remaining <= 0
    position = Position(
        symbol=symbol,
        direction=existing.direction,
        status=PositionStatus.CLOSED if closed else PositionStatus.OPEN,
        quantity=Decimal(0) if closed else remaining,
        average_entry=existing.average_entry,
        stop_price=existing.stop_price,
        target_price=existing.target_price,
        opened_at=existing.opened_at,
        closed_at=at if closed else None,
        fees_paid=existing.fees_paid + fee,
        realized_pnl=existing.realized_pnl + realized_delta,
        strategy_version=existing.strategy_version,
    )
    remaining_positions = _without(account.open_positions, symbol)
    if not closed:
        remaining_positions = (*remaining_positions, position)
    new_account = AccountState(
        cash=account.cash + exit_qty * fill_price - fee,
        open_positions=remaining_positions,
        realized_pnl_cum=account.realized_pnl_cum + realized_delta,
        fees_paid_cum=account.fees_paid_cum + fee,
        hwm_equity=account.hwm_equity,
    )
    return new_account, position


def with_hwm(account: AccountState, equity: Decimal) -> AccountState:
    """Return the account with HWM raised to ``equity`` if higher (never lowered)."""
    if equity <= account.hwm_equity:
        return account
    return AccountState(
        cash=account.cash,
        open_positions=account.open_positions,
        realized_pnl_cum=account.realized_pnl_cum,
        fees_paid_cum=account.fees_paid_cum,
        hwm_equity=equity,
    )
