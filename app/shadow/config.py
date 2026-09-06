"""Shadow Mode configuration (Phase 8 — source of truth).

Selects the (offline-by-default) data/news/AI sources and the shadow runtime
parameters. All real sources default to the offline ``fixture`` provider so the
package is safe to import and run with no network and no credentials. Fail-closed:
selecting a real source that needs an exchange id or is otherwise misconfigured
raises at construction (surfaced as a ``ConfigError`` at startup).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.market_data.models import Symbol, Timeframe
from app.shadow import SHADOW_ENGINE_VERSION


class MarketDataSource(StrEnum):
    FIXTURE = "fixture"  # offline, deterministic (default; the only one in tests)
    CCXT = "ccxt"  # real, public/keyless OHLCV; off by default


class NewsSource(StrEnum):
    FIXTURE = "fixture"  # offline (default)
    CRYPTOPANIC = "cryptopanic"  # real HTTP (documented provider); off by default


class AIProvider(StrEnum):
    FIXTURE = "fixture"  # offline (default)
    ANTHROPIC = "anthropic"  # real Anthropic SDK; off by default


@dataclass(frozen=True)
class ShadowConfig:
    """Shadow Mode runtime parameters + source selection (Phase 8)."""

    symbols: tuple[Symbol, ...]
    primary_timeframe: Timeframe = Timeframe.H1
    confirm_timeframe: Timeframe = Timeframe.H4
    starting_equity: Decimal = Decimal("10000")  # HYPOTHETICAL; flat per boundary
    warmup_buffer_candles: int = 100  # added to IndicatorConfig.min_history (§6.1)
    max_consecutive_data_failures: int = 3  # → PAUSE (§10/§11)
    backfill_boundaries: int = 0  # 0 → only the latest completed boundary (§10)
    clock_drift_seconds: int = 60  # exchange-vs-local drift → PAUSE (§18.1)
    market_data_source: MarketDataSource = MarketDataSource.FIXTURE
    market_data_exchange_id: str = ""  # required iff market_data_source == CCXT
    news_source: NewsSource = NewsSource.FIXTURE
    ai_provider: AIProvider = AIProvider.FIXTURE
    engine_version: str = field(default=SHADOW_ENGINE_VERSION)

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("shadow symbols must be non-empty")
        if self.primary_timeframe is self.confirm_timeframe:
            raise ValueError("primary_timeframe and confirm_timeframe must differ")
        if self.starting_equity <= 0:
            raise ValueError("shadow starting_equity must be > 0")
        if self.warmup_buffer_candles < 0:
            raise ValueError("warmup_buffer_candles must be >= 0")
        if self.max_consecutive_data_failures < 1:
            raise ValueError("max_consecutive_data_failures must be >= 1")
        if self.backfill_boundaries < 0:
            raise ValueError("backfill_boundaries must be >= 0")
        if self.clock_drift_seconds <= 0:
            raise ValueError("clock_drift_seconds must be > 0")
        # Fail-closed: a real CCXT source needs an explicit (data-source) exchange id.
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

    def warmup_min(self, indicator_min_history: int) -> int:
        """Required usable closed candles = IndicatorConfig.min_history + buffer (§6.1)."""
        return indicator_min_history + self.warmup_buffer_candles

    @property
    def version_tag(self) -> str:
        return (
            f"{self.engine_version}|tf{self.primary_timeframe.value}/{self.confirm_timeframe.value}"
            f"|buf{self.warmup_buffer_candles}|mds{self.market_data_source.value}"
            f"|news{self.news_source.value}|ai{self.ai_provider.value}"
        )
