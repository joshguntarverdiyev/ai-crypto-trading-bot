"""Shadow Mode alert builders (Phase 8) — outbound, read-only, never trades.

Pure builders that turn a ``ShadowResult`` / operational event into a redacted
``Alert`` for the existing ``Notifier``. They import no broker/engine/sizer and
create no orders. A would-be trade is explicitly labelled HYPOTHETICAL.
"""

from __future__ import annotations

from datetime import datetime

from app.notifications.models import Alert, AlertKind
from app.shadow.models import ShadowResult


def would_trade_alert(result: ShadowResult, *, at: datetime) -> Alert:
    """A HYPOTHETICAL would-be trade — recorded/announced, NOT executed."""
    return Alert(
        kind=AlertKind.SHADOW_WOULD_TRADE,
        title=f"HYPOTHETICAL would-be trade {result.symbol} (shadow — NOT executed)",
        fields={
            "symbol": str(result.symbol),
            "side": result.hyp_side or "",
            "quantity": str(result.hyp_quantity) if result.hyp_quantity is not None else "",
            "entry_ref": str(result.hyp_entry_ref) if result.hyp_entry_ref is not None else "",
            "hyp_fill_price": (
                str(result.hyp_fill_price) if result.hyp_fill_price is not None else ""
            ),
            "decision_time": result.decision_time.isoformat(),
            "note": "shadow mode: no order was placed",
        },
        at=at,
    )


def data_failure_alert(symbol: str, reason: str, *, consecutive: int, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.DATA_STALE,
        title="shadow data failure (no decision this boundary)",
        fields={"symbol": symbol, "reason": reason, "consecutive": str(consecutive)},
        at=at,
    )


def paused_alert(reason: str, *, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.KILL_PAUSED,
        title="shadow kill switch -> PAUSED",
        fields={"reason": reason},
        at=at,
    )


def halted_alert(reason: str, *, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.KILL_HALTED,
        title="shadow kill switch -> HALTED",
        fields={"reason": reason},
        at=at,
    )
