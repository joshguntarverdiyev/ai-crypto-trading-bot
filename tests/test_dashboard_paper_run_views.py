"""Dashboard additive per-run read views (P9 D-ISO) — read-only, offline.

The Claude/news/risk/events/orders/fills/universe/validation panels read the run's
OWN database (opened strictly ``mode=ro``), NOT the MAIN catalog DB. These tests seed
a real per-run DB via the P9 helpers, then assert each new GET endpoint renders the
authoritative data, fails closed on missing/unknown run_id, is physically read-only,
and never adds a mutating route. No network; the live run is never involved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.routing import Route

from app.database import session_scope
from app.market_data.models import Symbol
from app.paper.universe_build import build_and_persist_universe
from app.risk.kill_switch import KillSwitch
from app.universe.models import MarketInfo
from app.universe.provider import FixtureUniverseProvider
from dashboard import reads
from dashboard.app import create_app
from dashboard.config import DashboardConfig
from tests._p6_helpers import decision_now, exit_decision_time
from tests._p9_helpers import APPROVE, build_paper, paper_settings

T0 = datetime(2026, 9, 8, tzinfo=UTC)
_UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def _mkt(sym: str, vol: int) -> MarketInfo:
    s = Symbol.parse(sym)
    return MarketInfo(symbol=s, base=s.base, quote="USDT", active=True,
                      quote_volume_24h=Decimal(str(vol)))


def _seeded_run(tmp_path):
    """Create a real P9 run (catalog + run DB), process an entry+exit, freeze a universe."""
    settings = paper_settings(tmp_path, paper_universe_min_quote_volume=Decimal("0"))
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, settings=settings
    )
    runner.run_once(decision_now())        # entry (order/fill/decision/claude/risk/news)
    runner.run_once(exit_decision_time())  # exit
    markets = [_mkt(s, 900 - i) for i, s in enumerate(_UNIVERSE)]
    build_and_persist_universe(
        runner._sf, run_id, provider=FixtureUniverseProvider(markets),
        cfg=settings.paper_validation_config(), now=T0,
    )
    return run_id, main_sf, settings


def _client(main_sf, *, cfg=None) -> TestClient:
    return TestClient(create_app(
        session_factory=main_sf, kill_switch=KillSwitch(main_sf),
        config=DashboardConfig(), paper_validation_config=cfg,
    ))


# --- missing run_id → 422 (FastAPI required query param) -----------------------------
def test_missing_run_id_is_422(tmp_path) -> None:
    _run_id, main_sf, _s = _seeded_run(tmp_path)
    client = _client(main_sf)
    for path in ("claude", "news", "risk", "events", "orders", "fills",
                 "universe", "validation"):
        assert client.get(f"/api/paper/{path}").status_code == 422


# --- unknown run_id → empty / None, never an error ----------------------------------
def test_unknown_run_id_is_empty(tmp_path) -> None:
    _run_id, main_sf, _s = _seeded_run(tmp_path)
    client = _client(main_sf)
    for path in ("claude", "news", "risk", "events", "orders", "fills"):
        r = client.get(f"/api/paper/{path}", params={"run_id": "does-not-exist"})
        assert r.status_code == 200 and r.json() == []
    assert client.get("/api/paper/universe", params={"run_id": "nope"}).json() is None
    assert client.get("/api/paper/validation", params={"run_id": "nope"}).json() is None


# --- populated frozen run renders authoritative data --------------------------------
def test_populated_run_views(tmp_path) -> None:
    run_id, main_sf, _s = _seeded_run(tmp_path)
    client = _client(main_sf)

    # list endpoints all return JSON lists (Claude/news/risk/events are in the run DB)
    for path in ("claude", "news", "risk", "events", "orders", "fills"):
        body = client.get(f"/api/paper/{path}", params={"run_id": run_id}).json()
        assert isinstance(body, list)
    # an entry + exit definitely produced orders and paper decisions in the run DB
    assert client.get("/api/paper/orders", params={"run_id": run_id}).json()
    assert client.get("/api/paper/decisions", params={"run_id": run_id}).json()

    uni = client.get("/api/paper/universe", params={"run_id": run_id}).json()
    assert uni["count"] == len(_UNIVERSE)
    assert uni["selection_hash"] and uni["selection_hash_consistent"] is True
    assert uni["t0"].startswith("2026-09-08T00:00:00")  # authoritative T0 (tz round-trip naive)
    assert [row["symbol"] for row in uni["symbols"]] == _UNIVERSE  # by rank
    assert [row["rank"] for row in uni["symbols"]] == [0, 1, 2]


# --- validation reuses the authoritative evaluator; PENDING without cfg -------------
def test_validation_pending_without_cfg(tmp_path) -> None:
    run_id, main_sf, _s = _seeded_run(tmp_path)
    client = _client(main_sf, cfg=None)  # no validation config supplied
    body = client.get("/api/paper/validation", params={"run_id": run_id}).json()
    assert body["available"] is False and body["state"] == "PENDING"


def test_validation_with_cfg_returns_gates(tmp_path) -> None:
    run_id, main_sf, settings = _seeded_run(tmp_path)
    client = _client(main_sf, cfg=settings.paper_validation_config())
    body = client.get("/api/paper/validation", params={"run_id": run_id}).json()
    assert body["available"] in (True, False)
    if body["available"]:
        assert isinstance(body["gates"], list) and body["gates"]
        # gate statuses come from the ONE evaluator, never re-computed here
        assert all(g["status"] in {"pass", "fail", "insufficient_data"} for g in body["gates"])


# --- the per-run DB connection is physically read-only ------------------------------
def test_run_db_opened_read_only(tmp_path) -> None:
    run_id, main_sf, _s = _seeded_run(tmp_path)
    db_path = reads._catalog_row(main_sf, run_id)["db_path"]
    run_sf = reads._open_run_readonly(db_path)
    with pytest.raises(OperationalError):  # 'attempt to write a readonly database'
        with session_scope(run_sf) as s:
            s.execute(text("CREATE TABLE _dash_probe (x INTEGER)"))


# --- adding these routes did NOT add any mutating route -----------------------------
def test_still_exactly_two_mutating_routes(tmp_path) -> None:
    _run_id, main_sf, _s = _seeded_run(tmp_path)
    app = create_app(session_factory=main_sf, kill_switch=KillSwitch(main_sf),
                     config=DashboardConfig(auth_token="t"))
    mutating = sorted(
        r.path for r in app.routes
        if isinstance(r, Route) and r.methods and (r.methods & {"POST", "PUT", "PATCH", "DELETE"})
    )
    assert mutating == ["/control/halt", "/control/pause"]
