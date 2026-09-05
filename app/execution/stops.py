"""Paper stop-loss & target exit evaluation (Phase 6).

Bot-managed only — NO exchange-native/resting stops (P6). Deterministic from
candle OHLC. Long positions only (Master Plan §3). Produces a SELL exit `Intent`
(routed through the same broker path for uniform fills/fees/idempotency); the
broker then applies adverse spread + slippage.

Rules (H2): stop triggers on `low <= stop_price`, target on `high >=
target_price`. **Both touched in one candle → conservative stop-first.** Gap
handling: a stop gap-through fills at the worse open; a target ignores a
favorable gap and fills at the target price (never optimistic).
"""

from __future__ import annotations

from datetime import datetime

from app.execution.models import Intent, OrderSide, OrderType
from app.execution.paper_broker import make_intent_id
from app.market_data.models import Candle
from app.portfolio.models import Position


def compute_exit_intent(
    position: Position, candle: Candle, *, decision_time: datetime
) -> Intent | None:
    """Return a SELL exit intent for a long position, or None if no exit triggers."""
    stop_hit = candle.low <= position.stop_price
    target_hit = candle.high >= position.target_price
    if not stop_hit and not target_hit:
        return None

    if stop_hit:  # stop-first: stop dominates when both are touched (H2)
        order_type = OrderType.STOP
        # gap-through → fill at the worse (lower) of stop vs open
        reference = min(position.stop_price, candle.open)
    else:
        order_type = OrderType.TARGET
        # conservative: ignore a favorable gap; fill at the target price
        reference = position.target_price

    return Intent(
        intent_id=make_intent_id(
            decision_time=decision_time,
            symbol=position.symbol,
            side=OrderSide.SELL,
            order_type=order_type,
            tag=f"exit:{candle.close_time.isoformat()}",
        ),
        symbol=position.symbol,
        side=OrderSide.SELL,
        order_type=order_type,
        quantity=position.quantity,
        reference_price=reference,
        decision_time=decision_time,
    )
