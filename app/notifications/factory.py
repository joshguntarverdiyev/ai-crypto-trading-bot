"""Notifier construction from configuration (Phase 9 production wiring).

Turns a ``NotificationsConfig`` into a live ``Notifier`` (or ``None`` when
notifications are disabled), reusing the existing ``Notifier`` + transports — there
is NO parallel notification system here. Outbound only: inbound stop-controls remain
gated by ``cfg.allow_controls`` (default false) and are never enabled by this factory.

Selection:

* disabled            → ``None`` (callers pass this straight through; ``PaperRunner``
  already treats ``notifier=None`` as a no-op).
* enabled + ``http``  → real ``TelegramHttpTransport`` (bot token + chat id from config;
  ``httpx`` imported lazily; OFF unless explicitly configured).
* enabled + ``fixture`` → offline ``FixtureNotificationTransport`` (records in memory;
  no network — the default and the only transport used in tests).

The bot token is never logged here; ``secrets`` is forwarded to the ``Notifier`` so any
accidental token in alert text is redacted at format time.
"""

from __future__ import annotations

from app.notifications.config import NotificationsConfig, NotificationTransportKind
from app.notifications.http_transport import TelegramHttpTransport
from app.notifications.notifier import Notifier
from app.notifications.transport import FixtureNotificationTransport, NotificationTransport


def build_notifier(
    cfg: NotificationsConfig, *, secrets: tuple[str, ...] = ()
) -> Notifier | None:
    """Build the outbound ``Notifier`` from ``cfg``, or ``None`` when disabled."""
    if not cfg.enabled:
        return None
    transport: NotificationTransport
    if cfg.transport is NotificationTransportKind.HTTP:
        transport = TelegramHttpTransport(bot_token=cfg.bot_token, chat_id=cfg.chat_id)
    else:
        transport = FixtureNotificationTransport()
    return Notifier(transport, cfg, secrets=secrets)
