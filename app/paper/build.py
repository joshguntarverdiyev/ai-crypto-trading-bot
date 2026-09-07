"""Phase 9 paper-validation system factory — wires the runner from Settings.

Constructs the frozen P6 ``TradingEngine`` bound to a run's OWN database (per-run
isolation) plus the P9 ``PaperRunner``. Real adapters are constructed ONLY when
explicitly selected and are public/keyless (market data), CryptoPanic-behind-a-
conservative-settle-margin (news), or advisory-only (Claude). Fail-closed
(§35.15): refuses to build unless ``paper_validation_enabled`` is true AND
``live_trading``/``paper_trading`` are both false.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.ai.analyst import ClaudeAnalyst
from app.ai.config import AI_ANALYST_VERSION
from app.ai.fixture_provider import FixtureAnalystProvider
from app.ai.provider import AnalystProvider
from app.config import Settings
from app.costs.manager import CostManager
from app.engine.pipeline import TradingEngine
from app.engine.recorder import TickRecorder
from app.exceptions import ConfigError
from app.execution.paper_broker import PaperBroker
from app.execution.repository import PaperExecutionRepository
from app.ids import new_id
from app.indicators.config import INDICATOR_SET_VERSION
from app.indicators.features import FeatureBuilder
from app.market_data.adapter import ExchangeAdapter
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.repository import CandleRepository
from app.market_data.service import MarketDataService
from app.news.adapter import NewsSourceAdapter
from app.news.fixture_adapter import FixtureNewsAdapter
from app.news.service import NewsService
from app.paper import alerts
from app.paper.config import AIProvider, MarketDataSource, NewsSource, PaperValidationConfig
from app.paper.news_adapter import SettleMarginNewsAdapter
from app.paper.recorder import PaperRecorder
from app.paper.runner import PaperRunner
from app.paper.store import (
    acquire_run_lock,
    make_run_session_factory,
    open_paper_run,
    resume_paper_run,
)
from app.portfolio.store import PortfolioStore
from app.regime.classifier import RegimeClassifier
from app.risk.kill_switch import KillSwitch
from app.risk.manager import RiskManager
from app.sizing.config import SIZING_VERSION
from app.sizing.sizer import PositionSizer
from app.strategy.config import STRATEGY_VERSION
from app.strategy.generator import CandidateGenerator
from app.time_utils import utc_now


def _market_adapter(settings: Settings, cfg: PaperValidationConfig) -> ExchangeAdapter:
    if cfg.market_data_source is MarketDataSource.CCXT:
        from app.market_data.ccxt_adapter import CcxtMarketDataAdapter

        return CcxtMarketDataAdapter(
            exchange_id=cfg.market_data_exchange_id,
            symbols=list(cfg.symbols),
            timeframes=[cfg.primary_timeframe, cfg.confirm_timeframe],
        )
    return FixtureExchangeAdapter(
        ohlcv={}, symbols=list(cfg.symbols),
        timeframes=[cfg.primary_timeframe, cfg.confirm_timeframe],
    )


def _news_adapter(settings: Settings, cfg: PaperValidationConfig) -> NewsSourceAdapter:
    if cfg.news_source is NewsSource.CRYPTO_NEWS_API:
        # Tier-2: the decision-time read path is STORE-BACKED (no boundary network
        # I/O). The isolated ingestion store is populated by the separate poller
        # (scripts/run_news_ingest). available_at = max(published+settle, first_seen).
        from app.news.cryptonews_adapter import IngestionStoreNewsAdapter
        from app.news.ingestion import make_news_ingest_store

        store = make_news_ingest_store(settings.news_ingest_db_path)
        inner = IngestionStoreNewsAdapter(
            store, lookback_hours=settings.crypto_news_lookback_hours
        )
        return SettleMarginNewsAdapter(inner, settle_seconds=cfg.news_settle_seconds)
    if cfg.news_source is NewsSource.CRYPTOPANIC:
        from app.news.http_adapter import HttpNewsAdapter

        # Conservative settle margin (§35.8): never over-admit near-boundary news.
        return SettleMarginNewsAdapter(HttpNewsAdapter(), settle_seconds=cfg.news_settle_seconds)
    return FixtureNewsAdapter([])  # offline default → UNAVAILABLE → HOLD


def _analyst_provider(settings: Settings, cfg: PaperValidationConfig) -> AnalystProvider:
    if cfg.ai_provider is AIProvider.ANTHROPIC:
        from app.ai.anthropic_provider import AnthropicAnalystProvider

        return AnthropicAnalystProvider(api_key=settings.anthropic_api_key)
    return FixtureAnalystProvider("")  # offline default → schema_invalid → HOLD


def build_paper_system(
    settings: Settings,
    main_session_factory: sessionmaker[Session],
    *,
    run_id: str | None = None,
    notifier=None,
    market_adapter: ExchangeAdapter | None = None,
    news_adapter: NewsSourceAdapter | None = None,
    analyst_provider: AnalystProvider | None = None,
) -> tuple[PaperRunner, str]:
    """Build a ``PaperRunner`` + open/resume its run. Returns (runner, run_id).

    ``run_id=None`` starts a NEW isolated run; a given ``run_id`` resumes it.
    Adapters may be injected (tests); otherwise resolved from config (offline
    fixtures by default).
    """
    # Fail-closed flag matrix (§35.15): P9 runs ONLY under
    # (live_trading=False, paper_trading=False, paper_validation_enabled=True).
    if not settings.paper_validation_enabled:
        raise ConfigError(
            "Paper validation refuses to start: paper_validation_enabled is false."
        )
    if settings.live_trading:
        raise ConfigError("Paper validation refuses to start with live_trading enabled.")
    if settings.paper_trading:
        raise ConfigError("Paper validation refuses to start with paper_trading enabled.")

    cfg = settings.paper_validation_config()
    owner_token = new_id()
    versions = {
        "indicator_set_version": INDICATOR_SET_VERSION,
        "cost_model_version": settings.cost_config().version_tag,
        "strategy_version": STRATEGY_VERSION,
        "sizing_version": SIZING_VERSION,
        "risk_version": settings.risk_config().version_tag,
        "ai_analyst_version": AI_ANALYST_VERSION,
    }

    # OS file lock is the live single-writer guard (acquired before any catalog write).
    took_over = False
    if run_id is None:
        run_id = new_id()
        lock = acquire_run_lock(cfg, run_id)
        open_paper_run(
            main_session_factory, cfg, versions=versions, owner_token=owner_token, run_id=run_id
        )
        run_sf = make_run_session_factory(cfg, run_id, create=False)
    else:
        lock = acquire_run_lock(cfg, run_id)
        run_sf, took_over = resume_paper_run(
            main_session_factory, cfg, run_id, owner_token=owner_token
        )

    adapter = market_adapter or _market_adapter(settings, cfg)
    news = NewsService(news_adapter or _news_adapter(settings, cfg), settings.news_config())
    provider = analyst_provider or _analyst_provider(settings, cfg)

    market_service = MarketDataService(CandleRepository(run_sf))
    kill = KillSwitch(run_sf)  # this run's OWN kill switch (isolated)
    engine = TradingEngine(
        market_service=market_service,
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
        portfolio_store=PortfolioStore(run_sf, cfg.starting_equity),  # EVOLVING book (run DB)
        kill_switch=kill,
        recorder=TickRecorder(run_sf),
        exec_repo=PaperExecutionRepository(run_sf),
        cost_config=settings.cost_config(),
        cost_scenario=settings.default_cost_scenario(),
    )

    recorder = PaperRecorder(run_sf, cfg.starting_equity)
    runner = PaperRunner(
        engine=engine,
        recorder=recorder,
        kill_switch=kill,
        run_session_factory=run_sf,
        main_session_factory=main_session_factory,
        market_service=market_service,
        market_adapter=adapter,
        paper_config=cfg,
        feature_builder=FeatureBuilder(settings.indicator_config()),
        regime_classifier=RegimeClassifier(settings.regime_config()),
        run_id=run_id,
        owner_token=owner_token,
        notifier=notifier,
        secrets=tuple(settings.secret_values()),
    )
    runner._lock = lock  # hold the OS lock for the runner's lifetime

    if notifier is not None:
        notifier.send_alert(alerts.restart_alert(run_id, took_over=took_over, at=utc_now()))
    return runner, run_id
