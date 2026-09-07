"""Shared builders for Phase 9 paper-validation tests (offline, deterministic).

Reuses the P6 trade-producing candle scenario (``tests/_p6_helpers``) and wires a
real ``PaperRunner`` via ``build_paper_system`` with injected offline fixtures
(market data / news / analyst). Each run gets its own isolated SQLite file under a
temp ``paper_runs_dir``; the catalog lives in a temp main DB.
"""

from __future__ import annotations

import json
from datetime import timedelta

from app.ai.fixture_provider import FixtureAnalystProvider
from app.config import Settings, load_settings
from app.database import init_db, make_engine, make_session_factory
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.news.fixture_adapter import FixtureNewsAdapter
from app.news.models import NewsItemRaw
from app.paper.build import build_paper_system
from tests._p6_helpers import build_1h_raw, decision_now

APPROVE = json.dumps({
    "decision": "approve", "confidence": 0.9, "reason_codes": [],
    "affected_assets": ["BTC"], "event_risk": "low", "evidence": ["ok"],
})
VETO = json.dumps({
    "decision": "veto", "confidence": 0.9, "reason_codes": ["negative_high_impact_news"],
    "affected_assets": ["BTC"], "event_risk": "high", "evidence": ["bad"],
})


def paper_settings(tmp_path, **overrides) -> Settings:
    base: dict[str, object] = dict(
        environment="test",
        database_url=f"sqlite:///{tmp_path}/main.db",
        paper_runs_dir=f"{tmp_path}/runs",
        paper_validation_enabled=True,
        market_symbols=["BTC/USDT"],
        strategy_require_4h_confirmation=False,
        # widen caps so a valid candidate reaches APPROVE (exposure not the subject)
        risk_max_single_asset_exposure_pct=0.95,
        risk_max_total_exposure_pct=0.95,
        risk_correlated_exposure_cap_pct=0.95,
        sizing_max_single_asset_exposure_pct=0.95,
        sizing_max_total_exposure_pct=0.95,
        sizing_correlated_exposure_cap_pct=0.95,
    )
    base.update(overrides)
    return load_settings(_env_file=None, **base)


def main_factory(settings: Settings):
    engine = make_engine(settings.database_url)
    init_db(engine)
    return make_session_factory(engine)


def fixture_adapter(raw_1h=None) -> FixtureExchangeAdapter:
    return FixtureExchangeAdapter(
        ohlcv={
            ("BTC/USDT", "1h"): build_1h_raw() if raw_1h is None else raw_1h,
            ("BTC/USDT", "4h"): [],
        },
    )


def news_adapter(available: bool = True) -> FixtureNewsAdapter:
    if not available:
        return FixtureNewsAdapter([])
    avail = decision_now() - timedelta(hours=1)
    return FixtureNewsAdapter([
        NewsItemRaw(
            source="fixture", source_id="n1", title="BTC update",
            published_at=avail, available_at=avail, assets=("BTC",),
        )
    ])


def build_paper(
    tmp_path,
    *,
    analyst_response: str = APPROVE,
    raw_1h=None,
    news_available: bool = True,
    run_id: str | None = None,
    notifier=None,
    settings: Settings | None = None,
    main_sf=None,
):
    """Return (runner, run_id, main_sf, settings) for an offline P9 run."""
    settings = settings or paper_settings(tmp_path)
    main_sf = main_sf or main_factory(settings)
    runner, rid = build_paper_system(
        settings, main_sf, run_id=run_id, notifier=notifier,
        market_adapter=fixture_adapter(raw_1h),
        news_adapter=news_adapter(news_available),
        analyst_provider=FixtureAnalystProvider(analyst_response),
    )
    return runner, rid, main_sf, settings
