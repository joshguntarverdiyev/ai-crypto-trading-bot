"""All packages import cleanly; future-phase packages are importable but inert."""

from __future__ import annotations

import importlib

import pytest

CORE_MODULES = [
    "app",
    "app.config",
    "app.database",
    "app.exceptions",
    "app.logging_config",
    "app.time_utils",
    "app.ids",
    "app.main",
    "app.models",
    "app.models.base",
    "app.models.system_event",
    "app.models.error_record",
    "app.models.config_version",
]

FUTURE_PACKAGES = [
    "app.market_data", "app.indicators", "app.regime", "app.strategy",
    "app.costs", "app.news", "app.ai", "app.risk", "app.sizing",
    "app.execution", "app.tax", "app.portfolio", "app.engine",
    "app.notifications", "backtesting", "dashboard",
]


@pytest.mark.parametrize("name", CORE_MODULES + FUTURE_PACKAGES)
def test_module_imports(name: str) -> None:
    importlib.import_module(name)


@pytest.mark.parametrize("name", FUTURE_PACKAGES)
def test_future_packages_are_inert(name: str) -> None:
    module = importlib.import_module(name)
    public = [a for a in dir(module) if not a.startswith("_")]
    assert public == [], f"{name} should be empty in Phase 0, found {public}"
