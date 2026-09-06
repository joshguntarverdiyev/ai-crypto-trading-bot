"""Dashboard read views render offline from seeded P6 tables (plan §23/§30)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import session_scope
from app.models import PortfolioSnapshotRecord, PositionRecord
from app.risk.kill_switch import KillSwitch
from dashboard.app import create_app
from dashboard.config import DashboardConfig


def _seed(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add(
            PortfolioSnapshotRecord(
                snapshot_time=datetime(2026, 1, 2, tzinfo=UTC), cash=Decimal("9000"),
                equity=Decimal("10500"), total_exposure=Decimal("1500"),
                realized_pnl_cum=Decimal("500"), unrealized_pnl=Decimal("0"),
                fees_paid_cum=Decimal("12"), hwm_equity=Decimal("11000"),
                open_positions="[\"BTC/USDT\"]",
            )
        )
        session.add(
            PositionRecord(
                symbol="BTC/USDT", direction="long", status="open", quantity=Decimal("0.5"),
                average_entry=Decimal("3000"), stop_price=Decimal("2900"),
                target_price=Decimal("3300"), opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                closed_at=None, fees_paid=Decimal("3"), realized_pnl=Decimal("0"),
                strategy_version="strat-v1", updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )


def _client(db) -> TestClient:
    _engine, session_factory, _url = db
    _seed(session_factory)
    app = create_app(
        session_factory=session_factory,
        kill_switch=KillSwitch(session_factory),
        config=DashboardConfig(),
    )
    return TestClient(app)


def test_status_and_portfolio_views(db) -> None:
    client = _client(db)
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["kill_switch"]["status"] == "running"
    assert body["portfolio"]["equity"] == "10500"

    r = client.get("/api/portfolio")
    assert r.status_code == 200
    assert r.json()["drawdown_pct"] > 0  # equity below hwm


def test_positions_and_lists(db) -> None:
    client = _client(db)
    positions = client.get("/api/positions").json()
    assert positions and positions[0]["symbol"] == "BTC/USDT"
    for path in ("/api/orders", "/api/fills", "/api/risk", "/api/claude",
                 "/api/news", "/api/events", "/api/backtests"):
        r = client.get(path)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


def test_root_declares_read_only(db) -> None:
    client = _client(db)
    body = client.get("/").json()
    assert "cannot place" in body["note"].lower()
    assert body["controls_enabled"] is False
