"""Dashboard static visual UI (Step 2) — served, safe, read-only (offline).

Verifies the SPA is served at /ui/ with its assets, that GET / still returns JSON,
and that the shipped frontend contains no control-endpoint calls and no credentials.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.risk.kill_switch import KillSwitch
from dashboard.app import create_app
from dashboard.config import DashboardConfig

_STATIC = Path(__file__).resolve().parent.parent / "dashboard" / "static"


def _client(db) -> TestClient:
    _engine, session_factory, _url = db
    return TestClient(create_app(
        session_factory=session_factory, kill_switch=KillSwitch(session_factory),
        config=DashboardConfig(),
    ))


# --- 1/2. /ui/ serves index.html ----------------------------------------------------
def test_ui_index_served(db) -> None:
    r = _client(db).get("/ui/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "P9" in r.text and "AI" in r.text and "Trading Monitor" in r.text


# --- 3/4/5. css / js / vendor assets served -----------------------------------------
def test_ui_assets_served(db) -> None:
    client = _client(db)
    for path, needle in (
        ("/ui/css/terminal.css", "--bg"),
        ("/ui/js/app.js", "/paper/runs"),
        ("/ui/vendor/uPlot.min.js", "EquityChart"),
        ("/ui/vendor/uPlot.min.css", "chart-wrap"),
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        assert needle in r.text, path


# --- 6. GET / still returns its JSON identity ---------------------------------------
def test_root_json_unchanged(db) -> None:
    r = _client(db).get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["controls_enabled"] is False
    assert "cannot place, size, or modify a trade" in body["note"]


# --- 7. frontend never calls a control endpoint -------------------------------------
def test_frontend_has_no_control_calls() -> None:
    for f in _STATIC.rglob("*"):
        if f.suffix in {".js", ".html", ".css"}:
            text = f.read_text(encoding="utf-8")
            assert "/control" not in text, f.name
            assert "control/pause" not in text and "control/halt" not in text, f.name


# --- 8/9. no secrets; controls stay disabled ----------------------------------------
def test_frontend_has_no_secrets_and_controls_disabled(db) -> None:
    app_js = (_STATIC / "js" / "app.js").read_text(encoding="utf-8")
    index = (_STATIC / "index.html").read_text(encoding="utf-8")
    for needle in ("sk-ant", "ANTHROPIC_API_KEY", "bot_token", "api_key", "Bearer ",
                   "X-Auth-Token", "authorization"):
        assert needle.lower() not in app_js.lower(), needle
        assert needle.lower() not in index.lower(), needle
    # controls remain disabled at the API level
    assert _client(db).get("/").json()["controls_enabled"] is False


# --- 10. UI references the expected read-only /api/paper/* endpoints -----------------
def test_frontend_references_expected_endpoints() -> None:
    app_js = (_STATIC / "js" / "app.js").read_text(encoding="utf-8")
    for ep in ("/paper/runs", "/paper/portfolio", "/paper/positions", "/paper/decisions",
               "/paper/claude", "/paper/news", "/paper/risk", "/paper/events",
               "/paper/equity_curve", "/paper/metrics", "/paper/validation",
               "/paper/universe", "/paper/health"):
        assert ep in app_js, ep


# --- adding the static mount did NOT add a mutating route ----------------------------
def test_static_mount_adds_no_mutating_route(db) -> None:
    from starlette.routing import Route

    _engine, session_factory, _url = db
    app = create_app(session_factory=session_factory, kill_switch=KillSwitch(session_factory),
                     config=DashboardConfig(auth_token="t"))
    mutating = sorted(
        r.path for r in app.routes
        if isinstance(r, Route) and r.methods and (r.methods & {"POST", "PUT", "PATCH", "DELETE"})
    )
    assert mutating == ["/control/halt", "/control/pause"]
