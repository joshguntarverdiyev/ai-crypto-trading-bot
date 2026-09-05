"""Centralized, typed, fail-closed configuration (Phase 0 foundation).

Configuration is environment-driven (via ``.env`` / environment variables) and
validated with Pydantic v2. Safe-by-default:

* ``live_trading`` defaults to ``False`` and, in Phase 0, MUST be ``False`` —
  there is no execution layer, so any attempt to enable it fails at startup.
* No credential has a real default; placeholders are empty strings.
* Invalid configuration fails loudly at load time (fail-closed) rather than
  being silently coerced to a permissive value.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.exceptions import ConfigError

if TYPE_CHECKING:
    from app.costs.config import CostConfig, CostScenario
    from app.indicators.config import IndicatorConfig
    from app.regime.config import RegimeConfig
    from app.sizing.config import SizingConfig
    from app.strategy.config import StrategyConfig

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Environment(StrEnum):
    """Supported runtime environments for Phase 0.

    Future execution modes (paper, shadow, live) are represented by explicit
    boolean flags below and are all disabled/absent in Phase 0.
    """

    DEVELOPMENT = "development"
    TEST = "test"


class Settings(BaseSettings):
    """Application settings loaded from the environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- application / runtime ---
    environment: Environment = Environment.DEVELOPMENT
    app_name: str = "aicryptotrader"

    # --- logging ---
    log_level: str = "INFO"

    # --- database ---
    database_url: str = "sqlite:///./data/trading.db"

    # --- execution safety (Phase 0: all future modes disabled) ---
    live_trading: bool = False
    paper_trading: bool = False
    shadow_mode: bool = False

    # --- credential placeholders (MUST stay empty in the repo) ---
    exchange_api_key: str = ""
    exchange_api_secret: str = ""
    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- market data (Phase 1) ---
    market_symbols: list[str] = ["BTC/USDT", "ETH/USDT"]
    market_timeframes: list[str] = ["1h", "4h"]
    max_staleness_intervals: int = 1
    future_tolerance_seconds: int = 2
    ticker_staleness_seconds: int = 30

    # --- indicators / regime (Phase 2) ---
    ema_short: int = 50
    ema_long: int = 200
    rsi_period: int = 14
    atr_period: int = 14
    regime_trend_band: float = 0.002
    regime_vol_low_pct: float = 0.005
    regime_vol_high_pct: float = 0.02

    # --- cost model (Phase 3) — ILLUSTRATIVE, provisional, exchange-agnostic ---
    # Decimal-ratio percentages (0.001 = 0.1%). NOT a real/committed exchange
    # fee and NOT calibrated (calibration is P7). See app/costs/config.py.
    cost_taker_fee_pct: float = 0.001
    cost_maker_fee_pct: float = 0.0008
    cost_spread_fallback_pct: float = 0.0005
    cost_slippage_base_pct: float = 0.0005
    cost_slippage_opt_mult: float = 0.5
    cost_slippage_base_mult: float = 1.0
    cost_slippage_cons_mult: float = 2.0
    cost_atr_vol_coefficient: float = 0.1
    cost_atr_vol_cap_pct: float = 0.01
    cost_liquidity_buffer_pct: float = 0.0005
    cost_execution_uncertainty_pct: float = 0.0005
    cost_model_uncertainty_pct: float = 0.0005
    cost_safety_margin_pct: float = 0.0005
    cost_scenario: str = "conservative"

    # --- strategy (Phase 4) — provisional baseline, NOT calibrated (P7) ---
    # Baseline candidate hypothesis parameters (Master Plan §5). The ATR target
    # is a provisional model assumption, not a prediction. See app/strategy/config.py.
    strategy_rsi_pullback_level: float = 40.0
    strategy_stop_atr_mult: float = 1.5
    strategy_target_atr_mult: float = 3.0
    strategy_rr_threshold: float = 2.0
    strategy_require_4h_confirmation: bool = True

    # --- sizing (Phase 4) — ILLUSTRATIVE, exchange-agnostic, NOT calibrated ---
    # Advisory pre-runtime constraints only; never authorization to trade and
    # never a substitute for the future P6 RiskManager. See app/sizing/config.py.
    sizing_risk_per_trade_pct: float = 0.005
    sizing_max_single_asset_exposure_pct: float = 0.20
    sizing_max_total_exposure_pct: float = 0.30
    sizing_max_simultaneous_positions: int = 2
    sizing_correlated_exposure_cap_pct: float = 0.30
    sizing_min_notional: Decimal = Decimal("10")
    sizing_step_size: Decimal = Decimal("0.0001")
    sizing_tick_size: Decimal = Decimal("0.01")
    sizing_liquidity_cap_quote: Decimal = Decimal("100000")

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"log_level must be one of {sorted(_VALID_LOG_LEVELS)}, got {value!r}"
            )
        return upper

    @field_validator("market_symbols")
    @classmethod
    def _validate_symbols(cls, value: list[str]) -> list[str]:
        from app.market_data.models import Symbol  # local import avoids import cycle

        for item in value:
            Symbol.parse(item)  # raises ValueError on bad format
        return value

    @field_validator("market_timeframes")
    @classmethod
    def _validate_timeframes(cls, value: list[str]) -> list[str]:
        from app.market_data.models import Timeframe  # source of truth for validity

        for item in value:
            Timeframe(item)  # raises ValueError if not a supported timeframe
        return value

    @model_validator(mode="after")
    def _validate_indicator_params(self) -> Settings:
        if not (0 < self.ema_short < self.ema_long):
            raise ValueError("require 0 < ema_short < ema_long")
        if self.rsi_period <= 0 or self.atr_period <= 0:
            raise ValueError("rsi_period and atr_period must be > 0")
        if self.regime_trend_band <= 0:
            raise ValueError("regime_trend_band must be > 0")
        if not (0 < self.regime_vol_low_pct < self.regime_vol_high_pct):
            raise ValueError("require 0 < regime_vol_low_pct < regime_vol_high_pct")
        return self

    @model_validator(mode="after")
    def _validate_cost_params(self) -> Settings:
        from app.costs.config import CostScenario

        # CostConfig.__post_init__ is the source-of-truth for invariants; building
        # it here surfaces any violation as a fail-closed ConfigError at load time.
        self.cost_config()
        if self.cost_scenario not in {s.value for s in CostScenario}:
            raise ValueError(
                f"cost_scenario must be one of {[s.value for s in CostScenario]}, "
                f"got {self.cost_scenario!r}"
            )
        return self

    @model_validator(mode="after")
    def _validate_strategy_params(self) -> Settings:
        # StrategyConfig.__post_init__ is the source-of-truth for invariants;
        # building it here surfaces violations as a fail-closed ConfigError.
        self.strategy_config()
        return self

    @model_validator(mode="after")
    def _validate_sizing_params(self) -> Settings:
        # SizingConfig.__post_init__ is the source-of-truth for invariants.
        self.sizing_config()
        return self

    def indicator_config(self) -> IndicatorConfig:
        from app.indicators.config import IndicatorConfig

        return IndicatorConfig(
            ema_short=self.ema_short,
            ema_long=self.ema_long,
            rsi_period=self.rsi_period,
            atr_period=self.atr_period,
        )

    def regime_config(self) -> RegimeConfig:
        from app.regime.config import RegimeConfig

        return RegimeConfig(
            trend_band=self.regime_trend_band,
            vol_low_pct=self.regime_vol_low_pct,
            vol_high_pct=self.regime_vol_high_pct,
        )

    def cost_config(self) -> CostConfig:
        from app.costs.config import CostConfig

        return CostConfig(
            taker_fee_pct=self.cost_taker_fee_pct,
            maker_fee_pct=self.cost_maker_fee_pct,
            spread_fallback_pct=self.cost_spread_fallback_pct,
            slippage_base_pct=self.cost_slippage_base_pct,
            slippage_opt_mult=self.cost_slippage_opt_mult,
            slippage_base_mult=self.cost_slippage_base_mult,
            slippage_cons_mult=self.cost_slippage_cons_mult,
            atr_vol_coefficient=self.cost_atr_vol_coefficient,
            atr_vol_cap_pct=self.cost_atr_vol_cap_pct,
            liquidity_buffer_pct=self.cost_liquidity_buffer_pct,
            execution_uncertainty_pct=self.cost_execution_uncertainty_pct,
            model_uncertainty_pct=self.cost_model_uncertainty_pct,
            safety_margin_pct=self.cost_safety_margin_pct,
        )

    def default_cost_scenario(self) -> CostScenario:
        from app.costs.config import CostScenario

        return CostScenario(self.cost_scenario)

    def strategy_config(self) -> StrategyConfig:
        from app.strategy.config import StrategyConfig

        return StrategyConfig(
            rsi_pullback_level=self.strategy_rsi_pullback_level,
            stop_atr_mult=self.strategy_stop_atr_mult,
            target_atr_mult=self.strategy_target_atr_mult,
            rr_threshold=self.strategy_rr_threshold,
            require_4h_confirmation=self.strategy_require_4h_confirmation,
            cost_scenario=self.default_cost_scenario(),
        )

    def sizing_config(self) -> SizingConfig:
        from app.sizing.config import SizingConfig

        return SizingConfig(
            risk_per_trade_pct=self.sizing_risk_per_trade_pct,
            max_single_asset_exposure_pct=self.sizing_max_single_asset_exposure_pct,
            max_total_exposure_pct=self.sizing_max_total_exposure_pct,
            max_simultaneous_positions=self.sizing_max_simultaneous_positions,
            correlated_exposure_cap_pct=self.sizing_correlated_exposure_cap_pct,
            min_notional=self.sizing_min_notional,
            step_size=self.sizing_step_size,
            tick_size=self.sizing_tick_size,
            liquidity_cap_quote=self.sizing_liquidity_cap_quote,
        )

    @model_validator(mode="after")
    def _enforce_phase0_safety(self) -> Settings:
        # Fail-closed: Phase 0 has no execution layer. Live trading cannot be
        # enabled and there must be no ambiguity about it.
        if self.live_trading:
            raise ValueError(
                "LIVE_TRADING must be false in Phase 0 — no execution layer exists yet. "
                "Live trading is gated by the Master Plan's live-readiness criteria (P10/P11)."
            )
        return self

    def secret_values(self) -> list[str]:
        """Non-empty secret values, for log redaction. Never log this list."""
        candidates = [
            self.exchange_api_key,
            self.exchange_api_secret,
            self.anthropic_api_key,
            self.telegram_bot_token,
        ]
        return [c for c in candidates if c]


def load_settings(_env_file: str | None = ".env", **overrides: Any) -> Settings:
    """Load settings, converting Pydantic validation errors into ``ConfigError``.

    Pass ``_env_file=None`` to isolate from any on-disk ``.env`` (used in tests).
    """
    try:
        return Settings(_env_file=_env_file, **overrides)  # type: ignore[call-arg]
    except PydanticValidationError as exc:  # fail-closed at startup
        raise ConfigError(f"Invalid configuration: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton (loads from ``.env`` once)."""
    return load_settings()
