"""Notification domain types (Phase 7).

An ``Alert`` is an outbound operational message; a ``ControlCommand`` is the ONLY
kind of inbound command the notifier will act on — and it is restricted to the
stop direction (pause/halt). There is deliberately no order/trade command type
(Master Plan §17 / plan §24). Nothing here can place a trade.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AlertKind(StrEnum):
    FILL = "fill"  # a (paper) fill occurred
    RISK_REJECT = "risk_reject"  # RiskManager REJECT
    KILL_PAUSED = "kill_paused"  # kill switch -> PAUSED
    KILL_HALTED = "kill_halted"  # kill switch -> HALTED
    ERROR = "error"  # a critical system event / error
    DATA_STALE = "data_stale"  # data-freshness/staleness alert
    INFO = "info"  # generic operational note
    SHADOW_WOULD_TRADE = "shadow_would_trade"  # Phase 8: a HYPOTHETICAL would-be trade
    # Phase 9 — paper validation (evolving paper account; NO real trading)
    PAPER_ENTRY = "paper_entry"  # a paper entry was executed into the evolving book
    PAPER_EXIT = "paper_exit"  # a paper stop/target exit was executed
    PAPER_RESTART = "paper_restart"  # the paper runner (re)started / took over a run
    PAPER_RECOVERY = "paper_recovery"  # data/DB recovered after a failure streak
    PAPER_DRAWDOWN = "paper_drawdown"  # significant drawdown threshold crossed
    PAPER_HEARTBEAT = "paper_heartbeat"  # periodic liveness heartbeat


@dataclass(frozen=True)
class Alert:
    """An outbound operational alert. ``fields`` must be secret-free."""

    kind: AlertKind
    title: str
    fields: dict[str, str]
    at: datetime


class ControlAction(StrEnum):
    """Stop-direction-only actions. NO resume/reset here (privileged, out-of-band)."""

    PAUSE = "pause"
    HALT = "halt"


@dataclass(frozen=True)
class ControlCommand:
    """An inbound stop-direction-only control request (pause/halt only)."""

    action: ControlAction
    reason: str
    actor: str  # e.g. "telegram:<chat_id>" / "dashboard:<token-holder>"
