"""Phase 9 paper-validation alert builders (outbound, secret-free, never trade).

Pure builders that turn a boundary outcome / operational event into a redacted
``Alert`` for the existing ``Notifier``. They import no broker/engine/sizer and
create no orders. Paper activity is explicitly labelled as simulated (NOT real).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.notifications.models import Alert, AlertKind


def entry_alert(symbol: str, *, intent_id: str | None, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.PAPER_ENTRY,
        title=f"paper ENTRY {symbol} (simulated — no real order)",
        fields={"symbol": symbol, "intent_id": intent_id or "", "note": "paper validation"},
        at=at,
    )


def exit_alert(symbol: str, reason: str, *, intent_id: str | None, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.PAPER_EXIT,
        title=f"paper EXIT {symbol} ({reason}, simulated)",
        fields={"symbol": symbol, "reason": reason, "intent_id": intent_id or ""},
        at=at,
    )


def risk_reject_alert(symbol: str, reason: str, *, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.RISK_REJECT,
        title=f"paper risk REJECT {symbol}",
        fields={"symbol": symbol, "reason": reason},
        at=at,
    )


def data_failure_alert(symbol: str, reason: str, *, consecutive: int, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.DATA_STALE,
        title="paper data failure (no decision this boundary)",
        fields={"symbol": symbol, "reason": reason, "consecutive": str(consecutive)},
        at=at,
    )


def paused_alert(reason: str, *, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.KILL_PAUSED,
        title="paper kill switch -> PAUSED",
        fields={"reason": reason},
        at=at,
    )


def halted_alert(reason: str, *, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.KILL_HALTED,
        title="paper kill switch -> HALTED",
        fields={"reason": reason},
        at=at,
    )


def restart_alert(run_id: str, *, took_over: bool, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.PAPER_RESTART,
        title="paper runner started" + (" (took over stale run)" if took_over else ""),
        fields={"run_id": run_id, "took_over": str(took_over)},
        at=at,
    )


def recovery_alert(*, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.PAPER_RECOVERY,
        title="paper data recovered (failure streak reset)",
        fields={},
        at=at,
    )


def drawdown_alert(drawdown_pct: Decimal | float, *, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.PAPER_DRAWDOWN,
        title="paper significant drawdown",
        fields={"drawdown_pct": f"{float(drawdown_pct):.4f}"},
        at=at,
    )


def heartbeat_alert(run_id: str, *, at: datetime) -> Alert:
    return Alert(
        kind=AlertKind.PAPER_HEARTBEAT,
        title="paper runner heartbeat",
        fields={"run_id": run_id},
        at=at,
    )
