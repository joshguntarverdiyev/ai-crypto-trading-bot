"""Dashboard has EXACTLY two stop-only mutating routes and cannot trade (plan §23)."""

from __future__ import annotations

from pathlib import Path

from starlette.routing import Route

from app.risk.kill_switch import KillSwitch
from dashboard.app import create_app
from dashboard.config import DashboardConfig

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_DASH_DIR = Path(__file__).resolve().parent.parent / "dashboard"

_FORBIDDEN = (
    "app.execution",
    "app.engine",
    "app.sizing",
    "app.strategy",
    "app.costs",
    "backtesting.engine",
)


def test_exactly_two_mutating_routes_and_they_are_stop_only(db) -> None:
    _engine, session_factory, _url = db
    app = create_app(
        session_factory=session_factory, kill_switch=KillSwitch(session_factory),
        config=DashboardConfig(auth_token="t"),
    )
    mutating: list[str] = []
    for route in app.routes:
        if isinstance(route, Route) and route.methods:
            if route.methods & _MUTATING:
                mutating.append(route.path)
    assert sorted(mutating) == ["/control/halt", "/control/pause"]


def _import_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("from "):
            targets.append(line.split()[1])
        elif line.startswith("import "):
            targets.extend(p.strip().split()[0] for p in line[len("import "):].split(","))
    return targets


def test_dashboard_does_not_import_trading_runtime() -> None:
    for path in _DASH_DIR.glob("*.py"):
        targets = _import_targets(path.read_text(encoding="utf-8"))
        for forbidden in _FORBIDDEN:
            offenders = [t for t in targets if t == forbidden or t.startswith(forbidden + ".")]
            assert not offenders, f"{path.name} imports trading runtime {offenders!r}"
