"""Inbound controls are stop-direction-only (pause/halt), never trades (plan §24)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.notifications.config import NotificationsConfig
from app.notifications.models import ControlAction
from app.notifications.notifier import Notifier
from app.notifications.transport import FixtureNotificationTransport


class _FakeStop:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def pause(self, reason: str, at: datetime) -> None:
        self.calls.append(("pause", reason))

    def halt(self, reason: str, at: datetime) -> None:
        self.calls.append(("halt", reason))


def _notifier(*, allow_controls: bool) -> Notifier:
    return Notifier(
        FixtureNotificationTransport(),
        NotificationsConfig(enabled=True, allow_controls=allow_controls),
    )


@pytest.mark.parametrize("text", ["pause", "/pause hi", "HALT now", "halt"])
def test_parse_accepts_only_stop_commands(text: str) -> None:
    cmd = _notifier(allow_controls=True).parse_inbound(text, actor="telegram:1")
    assert cmd is not None
    assert cmd.action in (ControlAction.PAUSE, ControlAction.HALT)


@pytest.mark.parametrize(
    "text", ["buy BTC", "sell 1 ETH", "order market", "resume", "reset", "size 5", "", "status"]
)
def test_parse_rejects_everything_else(text: str) -> None:
    assert _notifier(allow_controls=True).parse_inbound(text, actor="telegram:1") is None


def test_apply_command_routes_to_stop_control_when_allowed() -> None:
    notifier = _notifier(allow_controls=True)
    stop = _FakeStop()
    cmd = notifier.parse_inbound("halt bad data", actor="telegram:1")
    assert cmd is not None
    assert notifier.apply_command(cmd, stop, at=datetime(2026, 1, 1, tzinfo=UTC)) is True
    assert stop.calls == [("halt", "bad data")]


def test_controls_disabled_do_not_actuate() -> None:
    notifier = _notifier(allow_controls=False)
    stop = _FakeStop()
    cmd = notifier.parse_inbound("pause", actor="telegram:1")
    assert cmd is not None
    assert notifier.apply_command(cmd, stop, at=datetime(2026, 1, 1, tzinfo=UTC)) is False
    assert stop.calls == []
