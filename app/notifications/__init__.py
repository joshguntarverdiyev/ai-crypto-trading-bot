"""app.notifications — Telegram operational alerts + stop-direction-only controls (Phase 7).

Outbound alerts (fills, risk/HALT/PAUSE, errors, data-freshness) and optional
inbound pause/halt controls, behind a ``NotificationTransport`` interface. The
offline ``FixtureNotificationTransport`` is the default and the only one used in
tests; the real HTTP transport is deferred/off and never invoked in tests.
Telegram NEVER trades (Master Plan §17 / plan §24).

Importing this package does NOT import ``httpx`` (the HTTP transport imports it
lazily), keeping the core import graph dependency-light.
"""

from __future__ import annotations

from app.notifications.config import NotificationsConfig, NotificationTransportKind
from app.notifications.models import Alert, AlertKind, ControlCommand
from app.notifications.notifier import Notifier
from app.notifications.transport import FixtureNotificationTransport, NotificationTransport

__all__ = [
    "NotificationsConfig",
    "NotificationTransportKind",
    "Alert",
    "AlertKind",
    "ControlCommand",
    "Notifier",
    "NotificationTransport",
    "FixtureNotificationTransport",
]
