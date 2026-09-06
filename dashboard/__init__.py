"""dashboard — FastAPI read-only monitoring + stop-direction-only controls (Phase 7).

Reads existing P6 audit tables and the P7 ``backtest_runs`` index; the ONLY
mutating endpoints are ``pause`` and ``halt`` (wired to the existing KillSwitch).
It NEVER places, sizes, or modifies an order/strategy/risk-limit and holds no
exchange/Claude credentials (Master Plan §17 / plan §23).

Note: importing this package does NOT import FastAPI. ``create_app`` is imported
lazily so the core ``app.*`` config graph stays FastAPI-free.
"""

from __future__ import annotations

from typing import Any

from dashboard.config import DashboardConfig

__all__ = ["DashboardConfig", "create_app"]


def __getattr__(name: str) -> Any:
    """Lazily expose ``create_app`` without importing FastAPI at package import.

    Keeps the core ``app.*`` config graph FastAPI-free (only ``dashboard.config``
    is imported by ``app.config``); FastAPI is pulled in only when a caller
    actually accesses ``dashboard.create_app``.
    """
    if name == "create_app":
        from dashboard.app import create_app as _create_app

        return _create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
