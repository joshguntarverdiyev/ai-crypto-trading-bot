"""PaperBroker — deterministic simulated execution (Phase 6).

Pure and deterministic (no RNG, no wall-clock, no persistence). Fill price uses
ONLY the reference price + adverse directional spread + adverse slippage (H1 — no
P3 gate buffers); fees are booked separately from the taker fee. Partial fills are
rule-based against the configured `liquidity_fill_cap` (H7). Idempotency and
persistence live in the repository/engine (§8), keeping this simulator pure.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from app.execution.config import PaperConfig
from app.execution.models import (
    ExecReason,
    ExecutionResult,
    Intent,
    OrderSide,
    OrderState,
    OrderType,
    PaperFill,
)
from app.market_data.models import Symbol


def make_intent_id(
    *, decision_time: datetime, symbol: Symbol, side: OrderSide, order_type: OrderType, tag: str
) -> str:
    basis = f"{decision_time.isoformat()}|{symbol}|{side.value}|{order_type.value}|{tag}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def _floor_to_step(qty: Decimal, step: Decimal) -> Decimal:
    return (qty / step).quantize(Decimal(1), rounding=ROUND_DOWN) * step


def _round_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick


class PaperBroker:
    def __init__(self, config: PaperConfig | None = None) -> None:
        self._cfg = config or PaperConfig()

    def simulate(
        self, intent: Intent, *, spread_pct: float, slippage_pct: float
    ) -> ExecutionResult:
        cfg = self._cfg

        def result(state: OrderState, reason: ExecReason, fills=()) -> ExecutionResult:
            return ExecutionResult(state, reason, intent, tuple(fills), reused=False)

        qty = _floor_to_step(intent.quantity, cfg.step_size)
        if qty <= 0:
            return result(OrderState.REJECTED, ExecReason.INVALID_QTY)

        # Partial fill to the configured liquidity cap (simulation assumption, H7).
        cap_qty = _floor_to_step(cfg.liquidity_fill_cap / intent.reference_price, cfg.step_size)
        fill_qty = min(qty, cap_qty)
        is_partial = fill_qty < qty
        if fill_qty <= 0:
            return result(OrderState.REJECTED, ExecReason.INVALID_QTY)

        # Adverse directional spread + slippage ONLY (H1). No P3 gate buffers.
        half_spread = Decimal(str(spread_pct)) / 2
        slip = Decimal(str(slippage_pct))
        if intent.side is OrderSide.BUY:
            factor = Decimal(1) + half_spread + slip
        else:
            factor = Decimal(1) - half_spread - slip
        fill_price = _round_to_tick(intent.reference_price * factor, cfg.tick_size)
        if fill_price <= 0:
            return result(OrderState.REJECTED, ExecReason.INVALID_QTY)

        notional = fill_qty * fill_price
        if notional < cfg.min_notional:
            return result(OrderState.REJECTED, ExecReason.BELOW_MIN_NOTIONAL)

        # Fee booked separately (H1), once, on executed notional.
        fee = (notional * Decimal(str(cfg.taker_fee_pct))).quantize(Decimal("0.00000001"))
        fill = PaperFill(fill_qty=fill_qty, fill_price=fill_price, fee=fee, is_partial=is_partial)
        state = OrderState.PARTIAL if is_partial else OrderState.FILLED
        reason = ExecReason.PARTIAL if is_partial else ExecReason.OK
        return result(state, reason, [fill])
