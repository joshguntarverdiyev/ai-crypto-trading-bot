"""Phase 9 paper-validation system factory — wires the runner from Settings.

Constructs the frozen P6 ``TradingEngine`` bound to a run's OWN database (per-run
isolation) plus the P9 ``PaperRunner``. Real adapters are constructed ONLY when
explicitly selected and are public/keyless (market data), CryptoPanic-behind-a-
conservative-settle-margin (news), or advisory-only (Claude). Fail-closed
(§35.15): refuses to build unless ``paper_validation_enabled`` is true AND
``live_trading``/``paper_trading`` are both false.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.ai.config import AI_ANALYST_VERSION
from app.ai.fixture_provider import FixtureAnalystProvider
from app.ai.provider import AnalystProvider
from app.config import Settings
from app.costs.manager import CostManager
from app.engine.pipeline import TradingEngine
from app.engine.recorder import TickRecorder
from app.exceptions import ConfigError, PaperRunError
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
from app.paper.budget import BudgetedAnalyst
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


def _claude_calls_so_far(run_sf: sessionmaker[Session]) -> int:
    """Durable per-run Claude call count (sum of persisted boundary funnel counters)
    so the per-run budget ceiling survives a restart."""
    from sqlalchemy import func, select

    from app.database import session_scope
    from app.models import PaperBoundaryFunnelRecord

    try:
        with session_scope(run_sf) as session:
            total = session.scalar(
                select(func.coalesce(func.sum(PaperBoundaryFunnelRecord.claude_calls), 0))
            )
            return int(total or 0)
    except Exception:
        return 0


def _effective_settings(settings: Settings, universe_symbols) -> Settings:  # noqa: ANN001
    """Route the authoritative T0 universe into ``market_symbols`` (the single source
    of truth) so the paper cfg, ``crypto_news_config().tickers`` and
    ``news_config().known_assets`` all derive from it. ``universe_symbols`` empty/None
    ⇒ the settings are returned unchanged (explicit BTC/ETH config preserved)."""
    if not universe_symbols:
        return settings
    # market_symbols = the universe; universe_enabled=True so the runner's
    # processing/priority order preserves the volume-rank order (not alphabetical).
    return settings.model_copy(
        update={
            "market_symbols": [str(s) for s in universe_symbols],
            "paper_universe_enabled": True,
        }
    )


def build_paper_system(
    settings: Settings,
    main_session_factory: sessionmaker[Session],
    *,
    run_id: str | None = None,
    notifier=None,
    market_adapter: ExchangeAdapter | None = None,
    news_adapter: NewsSourceAdapter | None = None,
    analyst_provider: AnalystProvider | None = None,
    universe_symbols=None,  # authoritative T0 universe (Symbols); None ⇒ use config
) -> tuple[PaperRunner, str]:
    """Build a ``PaperRunner`` + open/resume its run. Returns (runner, run_id).

    ``run_id=None`` starts a NEW isolated run; a given ``run_id`` resumes it.
    Adapters may be injected (tests); otherwise resolved from config (offline
    fixtures by default). ``universe_symbols`` (the frozen T0 selection) becomes the
    authoritative ``market_symbols`` so the news tickers + known-assets follow the
    universe; passing ``None`` preserves the configured (e.g. BTC/ETH) behavior.
    """
    # Wire the authoritative universe into market_symbols (single source of truth).
    settings = _effective_settings(settings, universe_symbols)

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

    # Claude cost control (P9 redesign): a budget-aware analyst (drop-in ClaudeAnalyst
    # subclass) capping ACTUAL provider calls per boundary + per run. Seed the per-run
    # count from durable funnel counters so the ceiling survives restart.
    budgeted = BudgetedAnalyst(
        settings.ai_config(), provider,
        max_per_boundary=cfg.claude_max_per_boundary,
        max_per_run=cfg.claude_max_per_run,
        run_calls_seed=_claude_calls_so_far(run_sf),
    )
    engine = TradingEngine(
        market_service=market_service,
        market_adapter=adapter,
        news_service=news,
        analyst=budgeted,
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
        budgeted_analyst=budgeted,
    )
    runner._lock = lock  # hold the OS lock for the runner's lifetime

    if notifier is not None:
        notifier.send_alert(alerts.restart_alert(run_id, took_over=took_over, at=utc_now()))
    return runner, run_id


def start_paper_system(
    settings: Settings,
    main_session_factory: sessionmaker[Session],
    *,
    now: datetime,
    run_id: str | None = None,
    universe_provider=None,  # noqa: ANN001 (MarketUniverseProvider; injected in tests)
    market_service=None,  # noqa: ANN001
    market_adapter: ExchangeAdapter | None = None,
    news_adapter: NewsSourceAdapter | None = None,
    analyst_provider: AnalystProvider | None = None,
    notifier=None,
):
    """P9 startup orchestrator. Returns ``(runner, run_id, universe_hash | None,
    universe_t0 | None)``, where ``universe_t0`` is the authoritative T0 of the frozen
    universe: ``now`` for a NEW run (== the persisted ``selected_at``), or the ORIGINAL
    persisted ``selected_at`` for a RESUME (NOT the current resume time). ``None`` for
    a standalone run.

    * ``universe_enabled=False`` (standalone/legacy) → unchanged ``build_paper_system``.
    * ``universe_enabled=True`` + NEW run → perform the T0 selection EXACTLY ONCE
      (``select_frozen_universe``), pass the frozen symbols to ``build_paper_system``,
      then persist THAT SAME Selection (``persist_universe``) into the run's own DB.
      Persistence failure closes the run and fails closed (never starts processing).
    * ``universe_enabled=True`` + RESUME (``run_id`` given) → load the already-frozen
      universe (verifying its hash) and reuse it; NO re-selection, no replacement.

    Fail-closed throughout (``PaperRunError``); never falls back to ``.env`` symbols
    for a P9 run."""
    cfg = settings.paper_validation_config()
    if not cfg.universe_enabled:
        runner, rid = build_paper_system(
            settings, main_session_factory, run_id=run_id, notifier=notifier,
            market_adapter=market_adapter, news_adapter=news_adapter,
            analyst_provider=analyst_provider,
        )
        return runner, rid, None, None

    from app.paper.store import close_paper_run
    from app.paper.universe_build import (
        load_frozen_universe,
        persist_universe,
        select_frozen_universe,
    )

    if run_id is None:  # NEW P9 run: ONE selection → build → persist that selection
        frozen = select_frozen_universe(
            settings, cfg, now=now, provider=universe_provider,
            market_service=market_service, market_adapter=market_adapter,
        )
        runner, rid = build_paper_system(
            settings, main_session_factory, universe_symbols=frozen.symbols,
            notifier=notifier, market_adapter=market_adapter, news_adapter=news_adapter,
            analyst_provider=analyst_provider,
        )
        try:
            persist_universe(runner._sf, rid, frozen, now)
        except Exception as exc:  # persistence failure → fail closed; do not process
            close_paper_run(main_session_factory, rid, status="stopped")
            raise PaperRunError(
                f"frozen-universe persistence failed for run_id={rid} (fail-closed): {exc}"
            ) from None
        return runner, rid, frozen.selection_hash, now  # NEW: T0 == selection time (now)

    # RESUME: reuse the already-frozen universe (verify hash + authoritative T0);
    # never re-select. universe_t0 is the ORIGINAL persisted selected_at, not `now`.
    symbols, universe_hash, frozen_t0 = load_frozen_universe(main_session_factory, run_id)
    runner, rid = build_paper_system(
        settings, main_session_factory, run_id=run_id, universe_symbols=symbols,
        notifier=notifier, market_adapter=market_adapter, news_adapter=news_adapter,
        analyst_provider=analyst_provider,
    )
    return runner, rid, universe_hash, frozen_t0
