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

from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.exceptions import ConfigError

if TYPE_CHECKING:
    from app.indicators.config import IndicatorConfig
    from app.regime.config import RegimeConfig

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
