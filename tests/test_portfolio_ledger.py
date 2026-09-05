"""Paper accounting ledger (H12): no double-counting of fees or PnL."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.market_data.models import Symbol
from app.portfolio import ledger
from app.portfolio.models import AccountState, PositionStatus
from app.strategy.models import SignalDirection

BTC = Symbol.parse("BTC/USDT")
DT = datetime(2026, 1, 2, tzinfo=UTC)


def _account(cash: str = "10000") -> AccountState:
    return AccountState(
        cash=Decimal(cash), open_positions=(), realized_pnl_cum=Decimal("0"),
        fees_paid_cum=Decimal("0"), hwm_equity=Decimal(cash),
    )


def _entry(acct, qty="10", price="100", fee="1"):
    return ledger.apply_entry(
        acct, symbol=BTC, direction=SignalDirection.LONG, fill_qty=Decimal(qty),
        fill_price=Decimal(price), fee=Decimal(fee), stop_price=Decimal("97"),
        target_price=Decimal("106"), strategy_version="strat-v1", at=DT,
    )


def test_entry_books_cash_and_fee_once() -> None:
    acct, pos = _entry(_account())
    assert acct.cash == Decimal("8999")  # 10000 - 1000 - 1
    assert acct.fees_paid_cum == Decimal("1")
    assert pos.quantity == Decimal("10") and pos.average_entry == Decimal("100")
    assert acct.equity({str(BTC): Decimal("100")}) == Decimal("9999")  # == 10000 - fee
    assert acct.unrealized_pnl({str(BTC): Decimal("100")}) == Decimal("0")


def test_entry_increase_recomputes_average() -> None:
    acct, _ = _entry(_account())
    acct2, pos = _entry(acct, qty="10", price="120", fee="1")
    assert pos.quantity == Decimal("20")
    assert pos.average_entry == Decimal("110")  # (10*100 + 10*120)/20


def test_full_exit_books_realized_pnl_and_closes() -> None:
    acct, _ = _entry(_account())
    acct2, pos = ledger.apply_exit(
        acct, symbol=BTC, exit_qty=Decimal("10"), fill_price=Decimal("110"),
        fee=Decimal("1"), at=DT,
    )
    assert pos.status is PositionStatus.CLOSED
    assert pos.realized_pnl == Decimal("99")  # 10*(110-100) - 1
    assert acct2.realized_pnl_cum == Decimal("99")
    assert acct2.fees_paid_cum == Decimal("2")  # entry fee + exit fee, each once
    assert acct2.cash == Decimal("10098")  # 8999 + 1100 - 1
    assert acct2.open_positions == ()


def test_partial_exit_keeps_remainder() -> None:
    acct, _ = _entry(_account())
    acct2, pos = ledger.apply_exit(
        acct, symbol=BTC, exit_qty=Decimal("4"), fill_price=Decimal("110"),
        fee=Decimal("0.5"), at=DT,
    )
    assert pos.status is PositionStatus.OPEN
    assert pos.quantity == Decimal("6")
    assert pos.realized_pnl == Decimal("39.5")  # 4*(110-100) - 0.5


def test_with_hwm_only_raises() -> None:
    acct = _account()
    assert ledger.with_hwm(acct, Decimal("9000")).hwm_equity == Decimal("10000")
    assert ledger.with_hwm(acct, Decimal("11000")).hwm_equity == Decimal("11000")
