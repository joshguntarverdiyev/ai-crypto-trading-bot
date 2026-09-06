"""Notifier — dispatch outbound alerts + parse stop-only inbound controls (Phase 7).

Outbound: formats (redacted) and sends an ``Alert`` via the configured transport.
Inbound: parses ONLY ``pause``/``halt`` (an allow-list); anything else is
rejected. Applying a control routes through a stop-direction-only interface
(``StopControl`` — structurally satisfied by the existing ``KillSwitch``). There
is no code path from a notification to placing/sizing/modifying an order — the
notifier never imports the broker/engine/sizer (Master Plan §17 / plan §24).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.notifications.config import NotificationsConfig
from app.notifications.formatter import format_alert
from app.notifications.models import Alert, ControlAction, ControlCommand
from app.notifications.transport import NotificationTransport


@runtime_checkable
class StopControl(Protocol):
    """Stop-direction-only control surface (a subset of ``KillSwitch``)."""

    def pause(self, reason: str, at: datetime) -> None: ...
    def halt(self, reason: str, at: datetime) -> None: ...


# The only inbound tokens the notifier will ever act on. Deliberately excludes
# anything that could open/size/modify a position.
_ALLOWED_COMMANDS = {"pause": ControlAction.PAUSE, "halt": ControlAction.HALT}


class Notifier:
    def __init__(
        self,
        transport: NotificationTransport,
        config: NotificationsConfig | None = None,
        *,
        secrets: tuple[str, ...] = (),
    ) -> None:
        self._transport = transport
        self._cfg = config or NotificationsConfig()
        self._secrets = secrets

    # --- outbound -------------------------------------------------------
    def send_alert(self, alert: Alert) -> bool:
        if not self._cfg.enabled:
            return False
        text = format_alert(alert, secrets=self._secrets)
        return self._transport.send(text)

    # --- inbound (stop-direction only) ----------------------------------
    def parse_inbound(self, text: str, *, actor: str) -> ControlCommand | None:
        """Parse an inbound message into a stop-only command, or None.

        Only ``pause`` / ``halt`` (optionally followed by a free-text reason) are
        recognized. Every other input — including anything resembling a trade —
        returns None (rejected).
        """
        stripped = text.strip()
        if not stripped:
            return None
        parts = stripped.split(maxsplit=1)
        head = parts[0].lower().lstrip("/")
        action = _ALLOWED_COMMANDS.get(head)
        if action is None:
            return None
        reason = parts[1].strip() if len(parts) > 1 else f"{head} via notifier"
        return ControlCommand(action=action, reason=reason, actor=actor)

    def apply_command(
        self, command: ControlCommand, control: StopControl, *, at: datetime
    ) -> bool:
        """Apply a stop-only command via the KillSwitch. Returns whether applied."""
        if not (self._cfg.enabled and self._cfg.allow_controls):
            return False
        if command.action is ControlAction.PAUSE:
            control.pause(command.reason, at)
        elif command.action is ControlAction.HALT:
            control.halt(command.reason, at)
        else:  # pragma: no cover - enum is exhaustive/stop-only
            return False
        return True
