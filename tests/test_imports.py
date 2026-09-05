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
    "app.models.candle",
    "app.models.types",
    # Phase 1 — market data (implemented)
    "app.market_data",
    "app.market_data.models",
    "app.market_data.validation",
    "app.market_data.adapter",
    "app.market_data.fixture_adapter",
    "app.market_data.repository",
    "app.market_data.service",
    # Phase 2 — indicators + regime (implemented)
    "app.indicators",
    "app.indicators.functions",
    "app.indicators.config",
    "app.indicators.models",
    "app.indicators.features",
    "app.regime",
    "app.regime.config",
    "app.regime.models",
    "app.regime.alignment",
    "app.regime.classifier",
    # Phase 3 — cost system (implemented)
    "app.costs",
    "app.costs.config",
    "app.costs.models",
    "app.costs.fees",
    "app.costs.spread",
    "app.costs.slippage",
    "app.costs.manager",
    # Phase 4 — strategy + sizing (implemented)
    "app.strategy",
    "app.strategy.config",
    "app.strategy.models",
    "app.strategy.generator",
    "app.sizing",
    "app.sizing.config",
    "app.sizing.models",
    "app.sizing.sizer",
    # Phase 5 — news + AI analyst (implemented, offline)
    "app.news",
    "app.news.config",
    "app.news.models",
    "app.news.adapter",
    "app.news.fixture_adapter",
    "app.news.normalization",
    "app.news.dedup",
    "app.news.service",
    "app.ai",
    "app.ai.config",
    "app.ai.models",
    "app.ai.provider",
    "app.ai.fixture_provider",
    "app.ai.schema",
    "app.ai.prompts",
    "app.ai.analyst",
]

FUTURE_PACKAGES = [
    "app.risk",
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
