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
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.models import SystemEvent
from app.notifications.notifier import StopControl
from app.time_utils import utc_now
from dashboard import reads
from dashboard.auth import make_control_guard
from dashboard.config import DashboardConfig

if TYPE_CHECKING:  # annotation only — not imported at runtime by the dashboard
    from app.paper.config import PaperValidationConfig


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
    paper_validation_config: PaperValidationConfig | None = None,
    static_dir: str | None = None,
) -> FastAPI:
    cfg = config or DashboardConfig()
    pvc = paper_validation_config  # authoritative gate config for /api/paper/validation
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

    @app.get("/api/shadow/decisions")
    def shadow_decisions(limit: int = 50) -> list[dict[str, object]]:
        return reads.recent_shadow_decisions(sf, limit)

    @app.get("/api/shadow/runs")
    def shadow_runs(limit: int = 25) -> list[dict[str, object]]:
        return reads.recent_shadow_runs(sf, limit)

    # --- Phase 9 paper-validation read views (per-run DB; read-only) ---
    @app.get("/api/paper/runs")
    def paper_runs(limit: int = 25) -> list[dict[str, object]]:
        return reads.paper_runs(sf, limit)

    @app.get("/api/paper/portfolio")
    def paper_portfolio(run_id: str) -> dict[str, object] | None:
        return reads.paper_portfolio(sf, run_id)

    @app.get("/api/paper/positions")
    def paper_positions(run_id: str) -> list[dict[str, object]]:
        return reads.paper_positions(sf, run_id)

    @app.get("/api/paper/decisions")
    def paper_decisions(run_id: str, limit: int = 50) -> list[dict[str, object]]:
        return reads.paper_decisions(sf, run_id, limit)

    @app.get("/api/paper/equity_curve")
    def paper_equity_curve(run_id: str) -> list[dict[str, object]]:
        return reads.paper_equity_curve(sf, run_id)

    @app.get("/api/paper/metrics")
    def paper_metrics(run_id: str) -> dict[str, object] | None:
        return reads.paper_metrics(sf, run_id)

    @app.get("/api/paper/health")
    def paper_health(run_id: str) -> dict[str, object] | None:
        return reads.paper_health(sf, run_id)

    # --- additive per-run audit views (read the run's OWN DB, read-only) ---
    # These populate the Claude/news/risk/events/orders/fills/universe/validation
    # panels for the live P9 run (whose audit rows live in the per-run DB, not the
    # MAIN catalog DB). All GET; all read-only; no external calls; no trade path.
    @app.get("/api/paper/claude")
    def paper_claude(run_id: str, limit: int = 50) -> list[dict[str, object]]:
        return reads.paper_claude(sf, run_id, limit)

    @app.get("/api/paper/news")
    def paper_news(run_id: str, limit: int = 50) -> list[dict[str, object]]:
        return reads.paper_news(sf, run_id, limit)

    @app.get("/api/paper/risk")
    def paper_risk(run_id: str, limit: int = 50) -> list[dict[str, object]]:
        return reads.paper_risk(sf, run_id, limit)

    @app.get("/api/paper/events")
    def paper_events(run_id: str, limit: int = 50) -> list[dict[str, object]]:
        return reads.paper_events(sf, run_id, limit)

    @app.get("/api/paper/orders")
    def paper_orders(run_id: str, limit: int = 50) -> list[dict[str, object]]:
        return reads.paper_orders(sf, run_id, limit)

    @app.get("/api/paper/fills")
    def paper_fills(run_id: str, limit: int = 50) -> list[dict[str, object]]:
        return reads.paper_fills(sf, run_id, limit)

    @app.get("/api/paper/universe")
    def paper_universe(run_id: str) -> dict[str, object] | None:
        return reads.paper_universe(sf, run_id)

    @app.get("/api/paper/validation")
    def paper_validation(run_id: str) -> dict[str, object] | None:
        return reads.paper_validation(sf, run_id, pvc)

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

    # --- static visual UI (read-only SPA) at /ui/ ---
    # StaticFiles is a GET/HEAD-only Mount (NOT a mutating Route), so the app still
    # has exactly two mutating routes. It only serves the packaged dashboard/static
    # assets; it introduces no trading path and no new API. GET "/" stays JSON.
    ui_dir = Path(static_dir) if static_dir else Path(__file__).resolve().parent / "static"
    if ui_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    return app
