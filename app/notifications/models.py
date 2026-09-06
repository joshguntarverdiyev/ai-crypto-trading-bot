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
