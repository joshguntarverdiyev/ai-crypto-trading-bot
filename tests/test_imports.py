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
    # Phase 6 — risk + paper engine (implemented, offline)
    "app.risk",
    "app.risk.config",
    "app.risk.models",
    "app.risk.manager",
    "app.risk.kill_switch",
    "app.execution",
    "app.execution.config",
    "app.execution.models",
    "app.execution.paper_broker",
    "app.execution.stops",
    "app.execution.repository",
    "app.portfolio",
    "app.portfolio.models",
    "app.portfolio.ledger",
    "app.portfolio.store",
    "app.engine",
    "app.engine.pipeline",
    "app.engine.recorder",
    # Phase 6 — new persistence models
    "app.models.news_record",
    "app.models.decisions",
    "app.models.paper",
    "app.models.portfolio",
    "app.models.kill_switch",
    # Phase 7 — backtesting (implemented, offline, pure-quant)
    "backtesting",
    "backtesting.version",
    "backtesting.config",
    "backtesting.models",
    "backtesting.dataset",
    "backtesting.costs",
    "backtesting.engine",
    "backtesting.metrics",
    "backtesting.statistics",
    "backtesting.robustness",
    "backtesting.walkforward",
    "backtesting.benchmark",
    "backtesting.report",
    "backtesting.store",
    # Phase 7 — backtest persistence model
    "app.models.backtest",
    # Phase 7 — notifications (implemented, offline fixture transport)
    "app.notifications",
    "app.notifications.config",
    "app.notifications.models",
    "app.notifications.transport",
    "app.notifications.formatter",
    "app.notifications.notifier",
    # Phase 7 — dashboard (implemented, read-only + stop-only controls)
    "dashboard",
    "dashboard.config",
    "dashboard.reads",
    "dashboard.auth",
    "dashboard.app",
]

FUTURE_PACKAGES = [
    "app.tax",
]


@pytest.mark.parametrize("name", CORE_MODULES + FUTURE_PACKAGES)
def test_module_imports(name: str) -> None:
    importlib.import_module(name)


@pytest.mark.parametrize("name", FUTURE_PACKAGES)
def test_future_packages_are_inert(name: str) -> None:
    module = importlib.import_module(name)
    public = [a for a in dir(module) if not a.startswith("_")]
    assert public == [], f"{name} should be empty in Phase 0, found {public}"
