"""P9 dashboard/Telegram isolation + no reachable live path."""

from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.database import session_scope
from app.models import PaperDecisionRecord, PaperTradingRunRecord
from app.notifications.config import NotificationsConfig, NotificationTransportKind
from app.notifications.models import ControlAction
from app.notifications.notifier import Notifier
from app.notifications.transport import FixtureNotificationTransport
from app.paper import alerts
from app.risk.kill_switch import KillSwitch
from app.time_utils import utc_now
from dashboard.app import create_app
from dashboard.reads import _open_run_readonly
from tests._p6_helpers import decision_now
from tests._p9_helpers import APPROVE, build_paper


def test_dashboard_paper_views_read_only(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path, analyst_response=APPROVE)
    runner.run_once(decision_now())
    app = create_app(session_factory=main_sf, kill_switch=KillSwitch(main_sf))
    client = TestClient(app)

    runs = client.get("/api/paper/runs").json()
    assert any(r["run_id"] == run_id for r in runs)
    health = client.get("/api/paper/health", params={"run_id": run_id}).json()
    assert health["run_id"] == run_id and health["decision_count"] >= 1
    # read views work; there is NO paper mutating endpoint (POST is not allowed)
    assert client.post("/api/paper/runs").status_code == 405
    assert client.post("/api/paper/portfolio", params={"run_id": run_id}).status_code == 405


def test_dashboard_run_db_connection_is_enforced_read_only(tmp_path) -> None:
    """The run-DB connection the dashboard opens is read-only at the SQLite level
    (mode=ro): reads work (WAL concurrent read) but ANY write is rejected — the
    dashboard can never mutate a P9 run DB even if a query tried to."""
    runner, run_id, main_sf, _settings = build_paper(tmp_path, analyst_response=APPROVE)
    runner.run_once(decision_now())  # sole writer creates + populates the run DB (WAL)

    with session_scope(main_sf) as s:
        catalog = s.get(PaperTradingRunRecord, run_id)
        assert catalog is not None
        db_path = catalog.db_path

    ro_sf = _open_run_readonly(db_path)

    # Reads keep working through the read-only connection.
    with session_scope(ro_sf) as s:
        decisions = s.scalars(select(PaperDecisionRecord)).all()
    assert len(decisions) >= 1

    # A write (schema-independent DDL probe) is blocked by the connection itself.
    with pytest.raises(OperationalError, match="readonly"):
        with session_scope(ro_sf) as s:
            s.execute(text("CREATE TABLE _dashboard_write_probe (id INTEGER)"))


def test_dashboard_only_two_mutations_are_stop_only(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path)
    app = create_app(session_factory=main_sf, kill_switch=KillSwitch(main_sf))
    mutating = [
        r.path for r in app.routes if getattr(r, "methods", None) and "POST" in r.methods
    ]
    assert set(mutating) == {"/control/pause", "/control/halt"}  # no buy/sell/paper mutation


def test_telegram_paper_alert_formats_and_cannot_trade() -> None:
    transport = FixtureNotificationTransport()
    notifier = Notifier(
        transport,
        NotificationsConfig(
            enabled=True, transport=NotificationTransportKind.FIXTURE, allow_controls=True
        ),
    )
    assert notifier.send_alert(alerts.entry_alert("BTC/USDT", intent_id="x", at=utc_now()))
    assert transport.sent and "paper_entry".upper() in transport.sent[-1]
    # inbound is stop-direction-only: a trade-like command is rejected.
    assert notifier.parse_inbound("buy BTC", actor="telegram:1") is None
    cmd = notifier.parse_inbound("pause", actor="telegram:1")
    assert cmd is not None and cmd.action is ControlAction.PAUSE


def test_no_live_or_trading_sdk_imported_by_paper() -> None:
    import app.paper.build  # noqa: F401
    import app.paper.metrics  # noqa: F401
    import app.paper.runner  # noqa: F401

    # Real market/AI SDKs are lazily imported ONLY when a real source is selected.
    assert "ccxt" not in sys.modules
    assert "anthropic" not in sys.modules
