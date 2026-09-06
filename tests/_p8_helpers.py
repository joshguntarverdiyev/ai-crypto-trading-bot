"""Shared builders for Phase 8 (Shadow Mode) tests — offline, deterministic.

Builds a ShadowEngine + ShadowRunner over FIXTURE adapters (no network, no
credentials). The 1h series is long enough to satisfy the warm-up minimum
(IndicatorConfig.min_history=200 + default buffer=100 → 300) and ends in a short
pullback so the strategy emits a long CANDIDATE, which — with a valid APPROVE
analyst response and wide caps — reaches a WOULD_TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.ai.analyst import ClaudeAnalyst
from app.ai.fixture_provider import FixtureAnalystProvider
from app.ai.provider import AnalystProvider, AnalystRequest
from app.config import Settings, load_settings
from app.costs.manager import CostManager
from app.execution.paper_broker import PaperBroker
from app.indicators.features import FeatureBuilder
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.models import RawCandle, Symbol, Timeframe
from app.market_data.repository import CandleRepository
from app.market_data.service import MarketDataService
from app.news.fixture_adapter import FixtureNewsAdapter
from app.news.models import NewsItemRaw
from app.news.service import NewsService
from app.regime.classifier import RegimeClassifier
from app.risk.kill_switch import KillSwitch
from app.risk.manager import RiskManager
from app.shadow.config import ShadowConfig
from app.shadow.engine import ShadowEngine
from app.shadow.recorder import ShadowRecorder
from app.shadow.runner import ShadowRunner
from app.sizing.sizer import PositionSizer
from app.strategy.generator import CandidateGenerator

BASE = datetime(2026, 1, 1, tzinfo=UTC)
SYMBOL = Symbol.parse("BTC/USDT")
N = 360  # >= warm-up min (300) with the default buffer

APPROVE_JSON = (
    '{"decision":"approve","confidence":0.9,"reason_codes":[],'
    '"affected_assets":["BTC"],"event_risk":"low","evidence":["ok"]}'
)


def build_1h_raw(
    symbol: str = "BTC/USDT", *, source: str = "fixture", n: int = N
) -> list[RawCandle]:
    prices: list[Decimal] = []
    p = Decimal("100")
    for _ in range(n - 20):  # long uptrend
        prices.append(p)
        p += Decimal("0.2")
    for _ in range(20):  # short pullback (drives RSI down; EMA50 stays > EMA200)
        p -= Decimal("1.0")
        prices.append(p)
    candles: list[RawCandle] = []
    for i in range(n):
        close = prices[i]
        open_ = prices[i - 1] if i > 0 else prices[0]
        hi = max(open_, close) * Decimal("1.01")
        lo = min(open_, close) * Decimal("0.99")
        candles.append(
            RawCandle(source, symbol, "1h", BASE + timedelta(hours=i),
                      str(open_), str(hi), str(lo), str(close), "10")
        )
    return candles


def decision_now(n: int = N) -> datetime:
    return BASE + timedelta(hours=n)


def approve_settings(**overrides: object) -> Settings:
    base: dict[str, object] = dict(
        strategy_require_4h_confirmation=False,
        risk_max_single_asset_exposure_pct=0.95,
        risk_max_total_exposure_pct=0.95,
        risk_correlated_exposure_cap_pct=0.95,
        sizing_max_single_asset_exposure_pct=0.95,
        sizing_max_total_exposure_pct=0.95,
        sizing_correlated_exposure_cap_pct=0.95,
    )
    base.update(overrides)
    return load_settings(_env_file=None, **base)


class CountingProvider(AnalystProvider):
    """Wraps a canned response; counts provider calls (for idempotency tests)."""

    def __init__(
        self, response: str = APPROVE_JSON, *, error: type[Exception] | None = None
    ) -> None:
        self._response = response
        self._error = error
        self.calls = 0

    def analyze(self, request: AnalystRequest) -> str:
        self.calls += 1
        if self._error is not None:
            raise self._error("counting provider failure")
        return self._response


@dataclass
class ShadowHarness:
    engine: ShadowEngine
    runner: ShadowRunner
    kill_switch: KillSwitch
    recorder: ShadowRecorder
    provider: AnalystProvider
    settings: Settings
    shadow_config: ShadowConfig


def build_shadow(
    session_factory,
    *,
    overrides: dict[str, object] | None = None,
    analyst_response: str | None = APPROVE_JSON,
    analyst_error: type[Exception] | None = None,
    news_available: bool = True,
    news_available_at: datetime | None = None,
    news_published_at: datetime | None = None,
    raw_1h: list[RawCandle] | None = None,
    raw_4h: list[RawCandle] | None = None,
    symbols: tuple[Symbol, ...] = (SYMBOL,),
    market_adapter=None,
    provider: AnalystProvider | None = None,
    notifier=None,
) -> ShadowHarness:
    settings = approve_settings(**(overrides or {}))
    sc = settings.shadow_config()
    sc = ShadowConfig(**{**sc.__dict__, "symbols": symbols})

    ohlcv: dict[tuple[str, str], list[RawCandle]] = {}
    for sym in symbols:
        ohlcv[(str(sym), "1h")] = (
            build_1h_raw(str(sym)) if raw_1h is None else raw_1h
        )
        ohlcv[(str(sym), "4h")] = raw_4h if raw_4h is not None else []
    adapter = market_adapter or FixtureExchangeAdapter(
        ohlcv=ohlcv, symbols=list(symbols), timeframes=[Timeframe.H1, Timeframe.H4]
    )

    dt = decision_now()
    avail = news_available_at if news_available_at is not None else dt - timedelta(hours=1)
    pub = news_published_at if news_published_at is not None else avail
    news_items = (
        [NewsItemRaw(source="fixture", source_id="n1", title="BTC update",
                     published_at=pub, available_at=avail, assets=("BTC",))]
        if news_available else []
    )
    news = NewsService(FixtureNewsAdapter(news_items), settings.news_config())

    prov = provider or (
        FixtureAnalystProvider(analyst_response or "", error=analyst_error)
    )

    engine = ShadowEngine(
        market_service=MarketDataService(CandleRepository(session_factory)),
        market_adapter=adapter,
        news_service=news,
        analyst=ClaudeAnalyst(settings.ai_config(), prov),
        feature_builder=FeatureBuilder(settings.indicator_config()),
        candidate_generator=CandidateGenerator(
            settings.strategy_config(), CostManager(settings.cost_config())
        ),
        sizer=PositionSizer(settings.sizing_config()),
        risk_manager=RiskManager(settings.risk_config()),
        paper_broker=PaperBroker(settings.paper_config()),
        regime_classifier=RegimeClassifier(settings.regime_config()),
        shadow_config=sc,
        indicator_config=settings.indicator_config(),
        cost_config=settings.cost_config(),
        cost_scenario=settings.default_cost_scenario(),
        require_confirm_warmup=settings.strategy_require_4h_confirmation,
    )
    kill = KillSwitch(session_factory)
    recorder = ShadowRecorder(session_factory)
    runner = ShadowRunner(
        engine=engine, recorder=recorder, kill_switch=kill,
        session_factory=session_factory, shadow_config=sc,
        market_adapter=adapter, notifier=notifier,
        secrets=tuple(settings.secret_values()),
    )
    return ShadowHarness(engine, runner, kill, recorder, prov, settings, sc)
