"""Shadow system factory (Phase 8) — wires the engine/runner from Settings.

Resolves the (offline-by-default) market-data / news / AI sources and constructs
the ``ShadowEngine`` + ``ShadowRunner`` reusing the frozen P1–P6 components. Real
adapters are constructed ONLY when explicitly selected and are public/keyless
(market data) or advisory-only (Claude). Fail-closed: refuses to build when
``live_trading`` or ``paper_trading`` is set (Shadow Mode never trades).
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.ai.analyst import ClaudeAnalyst
from app.ai.config import AI_ANALYST_VERSION
from app.ai.fixture_provider import FixtureAnalystProvider
from app.ai.provider import AnalystProvider
from app.config import Settings
from app.costs.manager import CostManager
from app.exceptions import ConfigError
from app.execution.paper_broker import PaperBroker
from app.indicators.config import INDICATOR_SET_VERSION
from app.indicators.features import FeatureBuilder
from app.market_data.adapter import ExchangeAdapter
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.repository import CandleRepository
from app.market_data.service import MarketDataService
from app.news.adapter import NewsSourceAdapter
from app.news.fixture_adapter import FixtureNewsAdapter
from app.news.service import NewsService
from app.regime.classifier import RegimeClassifier
from app.risk.kill_switch import KillSwitch
from app.risk.manager import RiskManager
from app.shadow.config import AIProvider, MarketDataSource, NewsSource, ShadowConfig
from app.shadow.engine import ShadowEngine
from app.shadow.recorder import ShadowRecorder
from app.shadow.runner import ShadowRunner
from app.shadow.store import open_shadow_run
from app.sizing.config import SIZING_VERSION
from app.sizing.sizer import PositionSizer
from app.strategy.config import STRATEGY_VERSION
from app.strategy.generator import CandidateGenerator


def _market_adapter(settings: Settings, cfg: ShadowConfig) -> ExchangeAdapter:
    if cfg.market_data_source is MarketDataSource.CCXT:
        from app.market_data.ccxt_adapter import CcxtMarketDataAdapter

        return CcxtMarketDataAdapter(
            exchange_id=cfg.market_data_exchange_id,
            symbols=list(cfg.symbols),
            timeframes=[cfg.primary_timeframe, cfg.confirm_timeframe],
        )
    # Offline default: an empty fixture (→ warm-up insufficient → HOLD), no network.
    return FixtureExchangeAdapter(
        ohlcv={}, symbols=list(cfg.symbols),
        timeframes=[cfg.primary_timeframe, cfg.confirm_timeframe],
    )


def _news_adapter(settings: Settings, cfg: ShadowConfig) -> NewsSourceAdapter:
    if cfg.news_source is NewsSource.CRYPTO_NEWS_API:
        # Store-backed read (no network at the boundary); populated by the poller.
        from app.news.cryptonews_adapter import IngestionStoreNewsAdapter
        from app.news.ingestion import make_news_ingest_store

        store = make_news_ingest_store(settings.news_ingest_db_path)
        return IngestionStoreNewsAdapter(
            store, lookback_hours=settings.crypto_news_lookback_hours
        )
    if cfg.news_source is NewsSource.CRYPTOPANIC:
        from app.news.http_adapter import HttpNewsAdapter

        return HttpNewsAdapter()  # public/free; no token committed
    return FixtureNewsAdapter([])  # offline default → UNAVAILABLE → HOLD


def _analyst_provider(settings: Settings, cfg: ShadowConfig) -> AnalystProvider:
    if cfg.ai_provider is AIProvider.ANTHROPIC:
        from app.ai.anthropic_provider import AnthropicAnalystProvider

        return AnthropicAnalystProvider(api_key=settings.anthropic_api_key)
    return FixtureAnalystProvider("")  # offline default → schema_invalid → HOLD


def build_shadow_system(
    settings: Settings,
    session_factory: sessionmaker[Session],
    *,
    notifier=None,
    market_adapter: ExchangeAdapter | None = None,
    news_adapter: NewsSourceAdapter | None = None,
    analyst_provider: AnalystProvider | None = None,
) -> tuple[ShadowRunner, str]:
    """Build a ``ShadowRunner`` + open a ``shadow_runs`` row. Returns (runner, run_id).

    Adapters may be injected (tests); otherwise they are resolved from config
    (offline fixtures by default).
    """
    # Fail-closed: Shadow Mode must never coincide with live/paper execution.
    if settings.live_trading:
        raise ConfigError("Shadow Mode refuses to start with live_trading enabled.")
    if settings.paper_trading:
        raise ConfigError("Shadow Mode refuses to start with paper_trading enabled.")

    cfg = settings.shadow_config()
    adapter = market_adapter or _market_adapter(settings, cfg)
    news = NewsService(news_adapter or _news_adapter(settings, cfg), settings.news_config())
    provider = analyst_provider or _analyst_provider(settings, cfg)

    engine = ShadowEngine(
        market_service=MarketDataService(CandleRepository(session_factory)),
        market_adapter=adapter,
        news_service=news,
        analyst=ClaudeAnalyst(settings.ai_config(), provider),
        feature_builder=FeatureBuilder(settings.indicator_config()),
        candidate_generator=CandidateGenerator(
            settings.strategy_config(), CostManager(settings.cost_config())
        ),
        sizer=PositionSizer(settings.sizing_config()),
        risk_manager=RiskManager(settings.risk_config()),
        paper_broker=PaperBroker(settings.paper_config()),
        regime_classifier=RegimeClassifier(settings.regime_config()),
        shadow_config=cfg,
        indicator_config=settings.indicator_config(),
        cost_config=settings.cost_config(),
        cost_scenario=settings.default_cost_scenario(),
        require_confirm_warmup=settings.strategy_require_4h_confirmation,
    )

    versions = {
        "indicator_set_version": INDICATOR_SET_VERSION,
        "cost_model_version": settings.cost_config().version_tag,
        "strategy_version": STRATEGY_VERSION,
        "sizing_version": SIZING_VERSION,
        "risk_version": settings.risk_config().version_tag,
        "ai_analyst_version": AI_ANALYST_VERSION,
    }
    run_id = open_shadow_run(session_factory, cfg, versions=versions)

    runner = ShadowRunner(
        engine=engine,
        recorder=ShadowRecorder(session_factory),
        kill_switch=KillSwitch(session_factory),
        session_factory=session_factory,
        shadow_config=cfg,
        market_adapter=adapter,
        notifier=notifier,
        secrets=tuple(settings.secret_values()),
        shadow_run_id=run_id,
    )
    return runner, run_id
