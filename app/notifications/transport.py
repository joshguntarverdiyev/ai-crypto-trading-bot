"""Notification transports (Phase 7).

A ``NotificationTransport`` sends a pre-formatted, redacted text message. The
default offline ``FixtureNotificationTransport`` records messages in memory (used
by tests and dev). The real Telegram HTTP transport lives in
``http_transport.py``, imports ``httpx`` lazily, is OFF by default, and is never
invoked in tests. Transports send text only — they cannot place trades.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class NotificationTransport(Protocol):
    """Sends a single text message. Returns True on success, False otherwise."""

    def send(self, text: str) -> bool: ...


class FixtureNotificationTransport:
    """Offline transport: records sent messages; performs NO network I/O."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> bool:
        self.sent.append(text)
        return True
