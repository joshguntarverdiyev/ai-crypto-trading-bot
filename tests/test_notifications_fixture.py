"""Telegram notifier over the offline fixture transport (Phase 7, plan §24)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.notifications.config import NotificationsConfig
from app.notifications.formatter import format_alert
from app.notifications.models import Alert, AlertKind
from app.notifications.notifier import Notifier
from app.notifications.transport import FixtureNotificationTransport


def _alert(**fields: str) -> Alert:
    return Alert(
        kind=AlertKind.FILL, title="paper fill", fields=fields,
        at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_enabled_notifier_sends_via_fixture_transport() -> None:
    transport = FixtureNotificationTransport()
    notifier = Notifier(transport, NotificationsConfig(enabled=True))
    assert notifier.send_alert(_alert(symbol="BTC/USDT", qty="0.5")) is True
    assert len(transport.sent) == 1
    assert "paper fill" in transport.sent[0]


def test_disabled_notifier_sends_nothing() -> None:
    transport = FixtureNotificationTransport()
    notifier = Notifier(transport, NotificationsConfig(enabled=False))
    assert notifier.send_alert(_alert()) is False
    assert transport.sent == []


def test_formatter_redacts_secrets() -> None:
    alert = _alert(token="SUPERSECRET", note="ok")
    text = format_alert(alert, secrets=("SUPERSECRET",))
    assert "SUPERSECRET" not in text
    assert "REDACTED" in text
