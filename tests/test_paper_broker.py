"""PaperBroker: deterministic fills, no P3 buffers in fill (H1), partial (H7)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.execution.config import PaperConfig
from app.execution.models import ExecutionResult, Intent, OrderSide, OrderState, OrderType
from app.execution.paper_broker import PaperBroker
from app.market_data.models import Symbol

BTC = Symbol.parse("BTC/USDT")
DT = datetime(2026, 1, 2, tzinfo=UTC)
CFG = PaperConfig(
    taker_fee_pct=0.001, tick_size=Decimal("0.01"), step_size=Decimal("0.0001"),
    min_notional=Decimal("10"), liquidity_fill_cap=Decimal("100000"),
)


def _sim(
    side: OrderSide, qty: str, ref: str, *, spread=0.0, slip=0.0, cfg=CFG
) -> ExecutionResult:
    intent = Intent("i1", BTC, side, OrderType.MARKET, Decimal(qty), Decimal(ref), DT)
    return PaperBroker(cfg).simulate(intent, spread_pct=spread, slippage_pct=slip)


def test_buy_fill_adds_spread_and_slippage_only() -> None:
    # H1: fill uses ref + half-spread + slippage ONLY; no P3 gate buffers.
    r = _sim(OrderSide.BUY, "10", "100", spread=0.01, slip=0.005)
    assert r.state is OrderState.FILLED
    fill = r.fills[0]
    # 100 * (1 + half_spread 0.005 + slippage 0.005) = 101.00
    assert fill.fill_price == Decimal("101.00")
    # fee booked separately: notional * taker
    expected_fee = (Decimal("10") * Decimal("101.00") * Decimal("0.001")).quantize(
        Decimal("0.00000001")
    )
    assert fill.fee == expected_fee


def test_sell_fill_is_adverse_downward() -> None:
    assert _sim(OrderSide.SELL, "10", "100", spread=0.01, slip=0.005).fills[0].fill_price \
        == Decimal("99.00")


def test_partial_fill_to_liquidity_cap() -> None:
    cfg = PaperConfig(liquidity_fill_cap=Decimal("500"), min_notional=Decimal("10"))
    r = _sim(OrderSide.BUY, "10", "100", cfg=cfg)
    assert r.state is OrderState.PARTIAL
    assert r.fills[0].is_partial is True
    assert r.fills[0].fill_qty == Decimal("5.0000")  # cap 500 / price 100


def test_reject_below_min_notional() -> None:
    r = _sim(OrderSide.BUY, "10", "100", cfg=PaperConfig(min_notional=Decimal("10000")))
    assert r.state is OrderState.REJECTED
    assert not r.fills


def test_reject_zero_quantity() -> None:
    # floored to step 0.0001 -> 0
    assert _sim(OrderSide.BUY, "0.00001", "100").state is OrderState.REJECTED


def test_deterministic() -> None:
    a = _sim(OrderSide.BUY, "10", "100", spread=0.01, slip=0.005)
    b = _sim(OrderSide.BUY, "10", "100", spread=0.01, slip=0.005)
    assert a.fills == b.fills and a.state == b.state
