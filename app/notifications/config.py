"""Notifications (Telegram) configuration (Phase 7 — source of truth).

Outbound operational alerts + optional stop-direction-only inbound controls,
behind a transport interface (Master Plan §17 / plan §24). The offline
``fixture`` transport is the default and the only one exercised in tests; the
``http`` transport is deferred/off and never invoked in tests. Telegram NEVER
trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class NotificationTransportKind(StrEnum):
    FIXTURE = "fixture"  # offline; records messages in-memory (tests/dev)
    HTTP = "http"  # real Telegram Bot API; off by default; never used in tests


@dataclass(frozen=True)
class NotificationsConfig:
    enabled: bool = False
    transport: NotificationTransportKind = NotificationTransportKind.FIXTURE
    allow_controls: bool = False  # honor inbound pause/halt only when true
    bot_token: str = ""  # empty in repo; required only for the http transport
    chat_id: str = ""  # allow-list target for inbound controls

    def __post_init__(self) -> None:
        # Fail-closed: the real HTTP transport must not be selected without creds.
        if (
            self.enabled
            and self.transport is NotificationTransportKind.HTTP
            and not (self.bot_token and self.chat_id)
        ):
            raise ValueError(
                "http transport requires bot_token and chat_id "
                "(keep empty in the repo; wire operationally)"
            )
