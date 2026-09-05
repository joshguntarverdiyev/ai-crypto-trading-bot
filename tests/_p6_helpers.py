"""Shared builders for Phase 6 tests (engine harness, candle series, fixtures).

Everything is offline and deterministic. The candle series is a long uptrend
followed by a short pullback so the strategy emits a long CANDIDATE (EMA50 >
EMA200, RSI in pullback, finite ATR% below the volatility-shock threshold).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.ai.analyst import ClaudeAnalyst
from app.ai.fixture_provider import FixtureAnalystProvider
from app.config import Settings, load_settings
from app.costs.manager import CostManager
from app.database import init_db, make_engine, make_session_factory
from app.engine.pipeline import TradingEngine
from app.engine.recorder import TickRecorder
from app.execution.paper_broker import PaperBroker
from app.execution.repository import PaperExecutionRepository
from app.indicators.features import FeatureBuilder
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.models import RawCandle, Symbol
from app.market_data.service import MarketDataService
from app.news.fixture_adapter import FixtureNewsAdapter
from app.news.models import NewsItemRaw
from app.news.service import NewsService
from app.portfolio.store import PortfolioStore
from app.risk.kill_switch import KillSwitch
from app.risk.manager import RiskManager
from app.sizing.sizer import PositionSizer
from app.strategy.generator import CandidateGenerator

BASE = datetime(2026, 1, 1, tzinfo=UTC)
SYMBOL = Symbol.parse("BTC/USDT")
N = 240


def build_1h_raw(symbol: str = "BTC/USDT", *, source: str = "fixture") -> list[RawCandle]:
    prices: list[Decimal] = []
    p = Decimal("100")
    for _ in range(N - 20):  # long uptrend
        prices.append(p)
        p += Decimal("0.2")
    for _ in range(20):  # short pullback (drives RSI down; EMA50 stays > EMA200)
        p -= Decimal("1.0")
        prices.append(p)
    candles: list[RawCandle] = []
    for i in range(N):
        close = prices[i]
        open_ = prices[i - 1] if i > 0 else prices[0]
        hi = max(open_, close) * Decimal("1.01")
        lo = min(open_, close) * Decimal("0.99")
        candles.append(
            RawCandle(
                source, symbol, "1h", BASE + timedelta(hours=i),
                str(open_), str(hi), str(lo), str(close), "10",
            )
        )
    return candles


def decision_now() -> datetime:
    return BASE + timedelta(hours=N)


def build_1h_raw_with_crash() -> list[RawCandle]:
    """The normal series plus one appended candle that gaps far below any stop,
    so an open long position's stop triggers on the last candle."""
    raw = build_1h_raw()
    raw.append(
        RawCandle(
            "fixture", "BTC/USDT", "1h", BASE + timedelta(hours=N),
            "124", "124", "1", "1", "10",
        )
    )
    return raw


def exit_decision_time() -> datetime:
    return BASE + timedelta(hours=N + 1)


def _news_adapter(decision_time: datetime, *, empty: bool = False) -> FixtureNewsAdapter:
    if empty:
        return FixtureNewsAdapter([])
    avail = decision_time - timedelta(hours=1)
    item = NewsItemRaw(
        source="fixture", source_id="n1", title="BTC update",
        published_at=avail, available_at=avail, assets=("BTC",),
    )
    return FixtureNewsAdapter([item])


def approve_settings(**overrides: object) -> Settings:
    base: dict[str, object] = dict(
        strategy_require_4h_confirmation=False,  # 4h warm-up covered by P4 tests
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


def make_session_factory_tmp(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/p6.db")
    init_db(engine)
    return make_session_factory(engine)


def build_engine(
    session_factory,
    settings: Settings,
    *,
    analyst_response: str | None = None,
    analyst_error=None,
    news_available: bool = True,
    raw_1h: list | None = None,
) -> TradingEngine:
    adapter = FixtureExchangeAdapter(
        ohlcv={
            ("BTC/USDT", "1h"): build_1h_raw() if raw_1h is None else raw_1h,
            ("BTC/USDT", "4h"): [],
        },
    )
    news_adapter = _news_adapter(decision_now(), empty=not news_available)
    provider = FixtureAnalystProvider(analyst_response or "", error=analyst_error)
    return TradingEngine(
        market_service=MarketDataService(),
        market_adapter=adapter,
        news_service=NewsService(news_adapter, settings.news_config()),
        analyst=ClaudeAnalyst(settings.ai_config(), provider),
        feature_builder=FeatureBuilder(settings.indicator_config()),
        candidate_generator=CandidateGenerator(
            settings.strategy_config(), CostManager(settings.cost_config())
        ),
        sizer=PositionSizer(settings.sizing_config()),
        risk_manager=RiskManager(settings.risk_config()),
        paper_broker=PaperBroker(settings.paper_config()),
        portfolio_store=PortfolioStore(session_factory, settings.paper_starting_equity),
        kill_switch=KillSwitch(session_factory),
        recorder=TickRecorder(session_factory),
        exec_repo=PaperExecutionRepository(session_factory),
        cost_config=settings.cost_config(),
        cost_scenario=settings.default_cost_scenario(),
    )
