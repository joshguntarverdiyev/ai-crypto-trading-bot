"""Dashboard controls: auth-gated, stop-direction only (plan §23/§25)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.risk.kill_switch import KillSwitch, KillSwitchStatus
from dashboard.app import create_app
from dashboard.config import DashboardConfig


def _client(db, *, token: str) -> tuple[TestClient, KillSwitch]:
    _engine, session_factory, _url = db
    ks = KillSwitch(session_factory)
    app = create_app(
        session_factory=session_factory, kill_switch=ks,
        config=DashboardConfig(auth_token=token),
    )
    return TestClient(app), ks


def test_controls_refused_when_no_token_configured(db) -> None:
    client, ks = _client(db, token="")
    r = client.post("/control/pause", json={"reason": "x"})
    assert r.status_code == 403  # controls disabled without a configured token
    assert ks.current().status is KillSwitchStatus.RUNNING


def test_wrong_token_is_unauthorized(db) -> None:
    client, ks = _client(db, token="s3cret")
    r = client.post("/control/halt", json={"reason": "x"}, headers={"X-Auth-Token": "nope"})
    assert r.status_code == 401
    assert ks.current().status is KillSwitchStatus.RUNNING


def test_correct_token_pauses_and_halts(db) -> None:
    client, ks = _client(db, token="s3cret")
    r = client.post("/control/pause", json={"reason": "manual"}, headers={"X-Auth-Token": "s3cret"})
    assert r.status_code == 200 and r.json()["action"] == "pause"
    assert ks.current().status is KillSwitchStatus.PAUSED

    r = client.post("/control/halt", json={"reason": "manual"}, headers={"X-Auth-Token": "s3cret"})
    assert r.status_code == 200 and r.json()["action"] == "halt"
    assert ks.current().status is KillSwitchStatus.HALTED


def test_control_action_is_audited(db) -> None:
    from sqlalchemy import select

    from app.database import session_scope
    from app.models import SystemEvent

    client, ks = _client(db, token="s3cret")
    client.post("/control/pause", json={"reason": "why"}, headers={"X-Auth-Token": "s3cret"})
    _engine, session_factory, _url = db
    with session_scope(session_factory) as session:
        events = session.scalars(
            select(SystemEvent).where(SystemEvent.component == "dashboard.control")
        ).all()
    assert any("pause" in e.message for e in events)
