"""Phase 8 dashboard shadow views — read-only; can never trade (offline)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import session_scope
from app.models import ShadowDecisionRecord, ShadowRunRecord
from app.risk.kill_switch import KillSwitch
from dashboard.app import create_app
from dashboard.config import DashboardConfig


def _seed(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add(
            ShadowRunRecord(
                run_time=datetime(2026, 1, 1, tzinfo=UTC), status="running",
                symbols='["BTC/USDT"]', timeframes='["1h","4h"]',
                market_data_source="fixture", news_source="fixture", ai_provider="fixture",
                engine_version="shadow-v1", indicator_set_version="ind-v1",
                cost_model_version="cost-v1", strategy_version="strat-v1",
                sizing_version="siz-v1", risk_version="risk-v1", ai_analyst_version="ai-v1",
                config_snapshot="{}",
            )
        )
        session.add(
            ShadowDecisionRecord(
                decision_time=datetime(2026, 1, 1, tzinfo=UTC), symbol="BTC/USDT",
                outcome="would_trade", stage="execution", reason="ok", regime="up/normal",
                market_summary="{}", features_summary="{}", hyp_side="buy",
                hyp_quantity=Decimal("0.1"), hyp_entry_ref=Decimal("100"),
                hyp_fill_price=Decimal("100.1"), hyp_fill_state="filled",
                engine_version="shadow-v1",
            )
        )


def _client(db) -> TestClient:
    _engine, session_factory, _url = db
    _seed(session_factory)
    app = create_app(
        session_factory=session_factory, kill_switch=KillSwitch(session_factory),
        config=DashboardConfig(),
    )
    return TestClient(app)


def test_shadow_views_render(db) -> None:
    client = _client(db)
    decisions = client.get("/api/shadow/decisions").json()
    assert decisions and decisions[0]["outcome"] == "would_trade"
    assert "not an executed trade" in decisions[0]["note"].lower()
    runs = client.get("/api/shadow/runs").json()
    assert runs and runs[0]["market_data_source"] == "fixture"


def test_no_shadow_mutating_route_exists(db) -> None:
    client = _client(db)
    # The only mutations remain the two stop-only controls; there is no shadow POST.
    app = client.app
    mutating = {
        (r.path, tuple(sorted(m for m in r.methods if m in {"POST", "PUT", "PATCH", "DELETE"})))
        for r in app.routes
        if getattr(r, "methods", None)
        and r.methods & {"POST", "PUT", "PATCH", "DELETE"}
    }
    assert mutating == {("/control/pause", ("POST",)), ("/control/halt", ("POST",))}
    # A shadow decision cannot be created via HTTP.
    assert client.post("/api/shadow/decisions").status_code in (404, 405)
