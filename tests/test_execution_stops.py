"""Paper stop/target exit evaluation (H2: both-touched → stop-first; gap)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.execution.models import OrderType
from app.execution.stops import compute_exit_intent
from app.market_data.models import Candle, Symbol, Timeframe
from app.portfolio.models import Position, PositionStatus
from app.strategy.models import SignalDirection

BTC = Symbol.parse("BTC/USDT")
DT = datetime(2026, 1, 2, tzinfo=UTC)


def _position(stop: str = "97", target: str = "106") -> Position:
    return Position(
        symbol=BTC, direction=SignalDirection.LONG, status=PositionStatus.OPEN,
        quantity=Decimal("10"), average_entry=Decimal("100"),
        stop_price=Decimal(stop), target_price=Decimal(target),
        opened_at=DT, closed_at=None, fees_paid=Decimal("0"),
        realized_pnl=Decimal("0"), strategy_version="strat-v1",
    )


def _candle(o: str, h: str, lo: str, c: str) -> Candle:
    return Candle(
        source="fixture", symbol=BTC, timeframe=Timeframe.H1, open_time=DT,
        open=Decimal(o), high=Decimal(h), low=Decimal(lo), close=Decimal(c), volume=Decimal("1"),
    )


def test_no_exit_when_neither_touched() -> None:
    candle = _candle("100", "104", "98", "101")
    assert compute_exit_intent(_position(), candle, decision_time=DT) is None


def test_stop_exit_fills_at_stop() -> None:
    intent = compute_exit_intent(_position(), _candle("100", "101", "96", "97"), decision_time=DT)
    assert intent is not None
    assert intent.order_type is OrderType.STOP
    assert intent.reference_price == Decimal("97")  # open (100) not below stop → fill at stop


def test_stop_gap_fills_at_worse_open() -> None:
    intent = compute_exit_intent(_position(), _candle("95", "96", "94", "95"), decision_time=DT)
    assert intent is not None
    assert intent.order_type is OrderType.STOP
    assert intent.reference_price == Decimal("95")  # gapped below stop → worse open


def test_target_exit_ignores_favorable_gap() -> None:
    intent = compute_exit_intent(_position(), _candle("108", "112", "107", "110"), decision_time=DT)
    assert intent is not None
    assert intent.order_type is OrderType.TARGET
    # conservative: fill at target, not the higher open
    assert intent.reference_price == Decimal("106")


def test_both_touched_is_stop_first() -> None:
    intent = compute_exit_intent(_position(), _candle("100", "107", "96", "101"), decision_time=DT)
    assert intent is not None
    assert intent.order_type is OrderType.STOP  # conservative stop-first (H2)
