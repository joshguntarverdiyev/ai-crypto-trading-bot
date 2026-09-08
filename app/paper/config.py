"""Phase 9 Paper Validation configuration (source of truth).

Selects the (offline-by-default) data/news/AI sources and the P9 runtime + gate
parameters. Reuses the P8 source enums (``MarketDataSource``/``NewsSource``/
``AIProvider``) unchanged. All real sources default to the offline ``fixture``
provider, so the package is safe to import and run with no network and no
credentials. Fail-closed: an invalid combination raises at construction
(surfaced as a ``ConfigError`` at startup).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.market_data.models import Symbol, Timeframe
from app.paper import PAPER_ENGINE_VERSION
from app.shadow.config import AIProvider, MarketDataSource, NewsSource

__all__ = [
    "PaperValidationConfig",
    "AIProvider",
    "MarketDataSource",
    "NewsSource",
]


@dataclass(frozen=True)
class PaperValidationConfig:
    """Phase 9 runtime parameters + source selection + validation gate thresholds."""

    symbols: tuple[Symbol, ...]
    primary_timeframe: Timeframe = Timeframe.H1
    confirm_timeframe: Timeframe = Timeframe.H4
    starting_equity: Decimal = Decimal("10000")  # evolving book seed (NOT flat, unlike P8)
    warmup_buffer_candles: int = 100  # added to IndicatorConfig.min_history
    max_consecutive_data_failures: int = 3  # → PAUSE
    clock_drift_seconds: int = 60  # exchange-vs-local drift → PAUSE
    news_settle_seconds: int = 120  # conservative availability margin (§35.8)
    owner_stale_intervals: int = 3  # heartbeat staleness (in boundaries) → takeover
    paper_runs_dir: str = "data/paper_runs"  # per-run DB files live here (D-ISO)

    market_data_source: MarketDataSource = MarketDataSource.FIXTURE
    market_data_exchange_id: str = ""  # required iff market_data_source == CCXT
    news_source: NewsSource = NewsSource.FIXTURE
    ai_provider: AIProvider = AIProvider.FIXTURE

    # Validation gate thresholds (objective; pre-registered per run — §35.4/§35.9).
    min_operational_days: int = 90
    min_uptime_fraction: float = 0.98
    max_unexplained_gaps: int = 24
    min_meaningful_trades: int = 100
    min_trades_per_regime_cell: int = 15
    rolling_buckets: int = 3  # chronological buckets for rolling-expectancy stability
    concentration_top_k: int = 3  # top-k trades removed for the concentration gate
    mc_max_drawdown_ceiling: float = 0.25  # pre-registered MC max-drawdown p95 ceiling (fraction)
    seed: int = 12345  # seeds bootstrap/Monte Carlo only (replay has no RNG)

    # --- Phase 9 redesign: multi-symbol universe + window + Claude budget ---
    validation_days: int = 90  # calendar-day validation window (10 for the redesign)
    universe_enabled: bool = False
    universe_quote: str = "USDT"
    universe_max_symbols: int = 30
    universe_min_quote_volume: Decimal = Decimal("5000000")
    universe_exchange_id: str = "binance"
    claude_max_per_boundary: int = 8
    claude_max_per_run: int = 5000

    engine_version: str = field(default=PAPER_ENGINE_VERSION)

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("paper symbols must be non-empty")
        if self.primary_timeframe is self.confirm_timeframe:
            raise ValueError("primary_timeframe and confirm_timeframe must differ")
        if self.starting_equity <= 0:
            raise ValueError("paper starting_equity must be > 0")
        if self.warmup_buffer_candles < 0:
            raise ValueError("warmup_buffer_candles must be >= 0")
        if self.max_consecutive_data_failures < 1:
            raise ValueError("max_consecutive_data_failures must be >= 1")
        if self.clock_drift_seconds <= 0:
            raise ValueError("clock_drift_seconds must be > 0")
        if self.news_settle_seconds < 0:
            raise ValueError("news_settle_seconds must be >= 0")
        if self.owner_stale_intervals < 1:
            raise ValueError("owner_stale_intervals must be >= 1")
        if self.min_operational_days < 1:
            raise ValueError("min_operational_days must be >= 1")
        if not (0.0 < self.min_uptime_fraction <= 1.0):
            raise ValueError("min_uptime_fraction must be in (0, 1]")
        if self.max_unexplained_gaps < 0:
            raise ValueError("max_unexplained_gaps must be >= 0")
        if self.min_meaningful_trades < 1:
            raise ValueError("min_meaningful_trades must be >= 1")
        if self.min_trades_per_regime_cell < 1:
            raise ValueError("min_trades_per_regime_cell must be >= 1")
        if self.rolling_buckets < 2:
            raise ValueError("rolling_buckets must be >= 2")
        if self.concentration_top_k < 1:
            raise ValueError("concentration_top_k must be >= 1")
        if not (0.0 < self.mc_max_drawdown_ceiling <= 1.0):
            raise ValueError("mc_max_drawdown_ceiling must be in (0, 1]")
        if self.validation_days < 1:
            raise ValueError("validation_days must be >= 1")
        if self.universe_max_symbols < 1:
            raise ValueError("universe_max_symbols must be >= 1")
        if self.claude_max_per_boundary < 1 or self.claude_max_per_run < 1:
            raise ValueError("claude budgets must be >= 1")
        # Fail-closed: a real CCXT source needs an explicit (public data-source) id.
        # This is NOT the deferred live-execution exchange choice (Master Plan §0.2-5).
        if self.market_data_source is MarketDataSource.CCXT and not self.market_data_exchange_id:
            raise ValueError(
                "market_data_source=ccxt requires market_data_exchange_id "
                "(a public data-source id, not a live-trading exchange choice)"
            )

    @property
    def canonical_symbols(self) -> tuple[Symbol, ...]:
        """Deterministic per-boundary processing order (input-order-independent)."""
        return tuple(sorted(self.symbols, key=str))

    @property
    def processing_order(self) -> tuple[Symbol, ...]:
        """Deterministic entry/budget priority order. When the universe is enabled the
        runner supplies ``symbols`` already in volume-rank order (highest 24h quote
        volume first); we preserve that order (stable-deduped). Otherwise fall back to
        the canonical sorted order. Idempotency is per ``(decision_time, symbol)`` and
        is unaffected by processing order."""
        if not self.universe_enabled:
            return self.canonical_symbols
        seen: set[str] = set()
        ordered: list[Symbol] = []
        for s in self.symbols:
            k = str(s)
            if k not in seen:
                seen.add(k)
                ordered.append(s)
        return tuple(ordered)

    def universe_config(self):  # noqa: ANN201 (return type imported lazily)
        from app.universe.config import UniverseConfig

        return UniverseConfig(
            quote=self.universe_quote,
            max_symbols=self.universe_max_symbols,
            min_quote_volume=self.universe_min_quote_volume,
        )

    def warmup_min(self, indicator_min_history: int) -> int:
        """Required usable closed candles = IndicatorConfig.min_history + buffer."""
        return indicator_min_history + self.warmup_buffer_candles

    @property
    def version_tag(self) -> str:
        return (
            f"{self.engine_version}|tf{self.primary_timeframe.value}/{self.confirm_timeframe.value}"
            f"|buf{self.warmup_buffer_candles}|settle{self.news_settle_seconds}"
            f"|mds{self.market_data_source.value}|news{self.news_source.value}"
            f"|ai{self.ai_provider.value}"
        )
