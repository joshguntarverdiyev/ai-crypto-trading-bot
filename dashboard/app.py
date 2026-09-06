"""Read-only monitoring dashboard + stop-direction-only controls (Phase 7).

FastAPI app factory. GET endpoints render existing P6 audit tables + the P7
``backtest_runs`` index. The ONLY mutating endpoints are ``POST /control/pause``
and ``POST /control/halt``, which route through the existing ``KillSwitch`` (a
stop-direction-only surface) and write a control-audit ``SystemEvent``. There is
NO endpoint that can place/size/modify an order, strategy, or risk limit, and the
app holds no exchange/Claude credentials (Master Plan §17 / plan §23).
"""

from __future__ import annotations

import json

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.models import SystemEvent
from app.notifications.notifier import StopControl
from app.time_utils import utc_now
from dashboard import reads
from dashboard.auth import make_control_guard
from dashboard.config import DashboardConfig


class ControlRequest(BaseModel):
    reason: str = "manual"


def _audit_control(sf: sessionmaker[Session], action: str, reason: str) -> None:
    with session_scope(sf) as session:
        session.add(
            SystemEvent(
                level="WARNING",
                component="dashboard.control",
                message=f"dashboard control: {action}",
                context=json.dumps({"actor": "dashboard", "reason": reason, "action": action}),
            )
        )


def create_app(
    *,
    session_factory: sessionmaker[Session],
    kill_switch: StopControl,
    config: DashboardConfig | None = None,
) -> FastAPI:
    cfg = config or DashboardConfig()
    guard = make_control_guard(cfg)
    app = FastAPI(title="aicryptotrader dashboard (read-only)", version="p7")
    sf = session_factory

    @app.get("/")
    def root() -> dict[str, object]:
        return {
            "app": "aicryptotrader dashboard",
            "mode": "read-only + stop-direction-only controls",
            "controls_enabled": cfg.controls_enabled,
            "note": "This dashboard cannot place, size, or modify a trade.",
        }

    @app.get("/api/status")
    def status() -> dict[str, object]:
        return reads.status_overview(sf)

    @app.get("/api/portfolio")
    def portfolio() -> dict[str, object] | None:
        return reads.latest_portfolio(sf)

    @app.get("/api/positions")
    def positions() -> list[dict[str, object]]:
        return reads.open_positions(sf)

    @app.get("/api/orders")
    def orders(limit: int = 50) -> list[dict[str, object]]:
        return reads.recent_paper_orders(sf, limit)

    @app.get("/api/fills")
    def fills(limit: int = 50) -> list[dict[str, object]]:
        return reads.recent_paper_fills(sf, limit)

    @app.get("/api/risk")
    def risk(limit: int = 50) -> list[dict[str, object]]:
        return reads.recent_risk_decisions(sf, limit)

    @app.get("/api/claude")
    def claude(limit: int = 50) -> list[dict[str, object]]:
        return reads.recent_claude_decisions(sf, limit)

    @app.get("/api/news")
    def news(limit: int = 50) -> list[dict[str, object]]:
        return reads.recent_news(sf, limit)

    @app.get("/api/events")
    def events(limit: int = 50) -> list[dict[str, object]]:
        return reads.recent_system_events(sf, limit)

    @app.get("/api/backtests")
    def backtests(limit: int = 25) -> list[dict[str, object]]:
        return reads.recent_backtest_runs(sf, limit)

    # --- the ONLY two mutating endpoints (stop-direction only) ---
    @app.post("/control/pause")
    def control_pause(body: ControlRequest, _: None = Depends(guard)) -> dict[str, object]:
        _audit_control(sf, "pause", body.reason)
        kill_switch.pause(f"dashboard:{body.reason}", utc_now())
        return {"ok": True, "action": "pause"}

    @app.post("/control/halt")
    def control_halt(body: ControlRequest, _: None = Depends(guard)) -> dict[str, object]:
        _audit_control(sf, "halt", body.reason)
        kill_switch.halt(f"dashboard:{body.reason}", utc_now())
        return {"ok": True, "action": "halt"}

    return app
