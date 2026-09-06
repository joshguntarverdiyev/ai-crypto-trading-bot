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

from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.exceptions import ConfigError

if TYPE_CHECKING:
    from app.ai.config import AIConfig
    from app.costs.config import CostConfig, CostScenario
    from app.execution.config import PaperConfig
    from app.indicators.config import IndicatorConfig
    from app.news.config import NewsConfig
    from app.notifications.config import NotificationsConfig
    from app.regime.config import RegimeConfig
    from app.risk.config import RiskConfig
    from app.sizing.config import SizingConfig
    from app.strategy.config import StrategyConfig
    from backtesting.config import BacktestConfig

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

    # --- news pipeline (Phase 5) — offline; provisional, NOT calibrated ---
    news_max_age_seconds: int = 86400  # 24h freshness window
    news_dedup_window_seconds: int = 172800  # 48h dedup window
    news_require_known_availability: bool = True  # fail-safe: exclude unknown (§7)
    news_known_assets: list[str] = ["BTC", "ETH"]

    # --- AI analyst (Phase 5) — class-based model abstraction (§0.1-2) ---
    # Model IDs are config-driven (never hardcoded in logic); re-verified when the
    # real provider is wired. The anthropic_api_key placeholder stays empty (no
    # credential; no live call in Phase 5).
    ai_analyst_enabled: bool = True
    ai_analyst_model_class: str = "sonnet"
    ai_haiku_model_id: str = "claude-haiku-4-5-20251001"
    ai_sonnet_model_id: str = "claude-sonnet-4-6"
    ai_opus_model_id: str = "claude-opus-4-8"
    ai_timeout_seconds: float = 20.0
    ai_uncertain_policy: str = "hold"

    # --- risk manager (Phase 6) — final authority; provisional, NOT calibrated ---
    risk_max_risk_per_trade_pct: float = 0.01
    risk_max_single_asset_exposure_pct: float = 0.20
    risk_max_total_exposure_pct: float = 0.30
    risk_max_simultaneous_positions: int = 2
    risk_correlated_exposure_cap_pct: float = 0.30
    risk_max_daily_loss_pct: float = 0.03
    risk_max_weekly_loss_pct: float = 0.06
    risk_max_drawdown_pct: float = 0.15
    risk_vol_shock_atr_pct: float = 0.10
    risk_abnormal_spread_pct: float = 0.01
    risk_abnormal_slippage_pct: float = 0.01
    risk_max_staleness_intervals: int = 1

    # --- paper engine (Phase 6) — simulation only; LIVE_TRADING stays false ---
    paper_liquidity_fill_cap: Decimal = Decimal("100000")  # simulation assumption (H7)
    paper_starting_equity: Decimal = Decimal("10000")

    # --- backtesting (Phase 7) — offline, deterministic, pure-quant; NOT calibrated ---
    # Research tooling only: no trading, no calibration/optimization, no edge claim.
    backtest_dataset_name: str = "example"
    backtest_starting_equity: Decimal = Decimal("10000")
    backtest_cost_scenario: str = "conservative"  # headline scenario (§10/§12)
    backtest_seed: int = 12345  # seeds bootstrap/Monte Carlo only (replay has no RNG)
    backtest_halt_policy: str = "end_run"  # end_run (default) | reset_next_period
    backtest_entry_fill_rule: str = "next_open"  # next_open (default) | signal_close (§10)
    backtest_min_operational_trades: int = 100  # operational floor; NOT significance
    backtest_artifacts_dir: str = "data/backtests"

    # --- dashboard (Phase 7) — read-only + stop-direction-only controls (§17/§23) ---
    dashboard_enabled: bool = False
    dashboard_host: str = "127.0.0.1"  # loopback by default; never public
    dashboard_port: int = 8787
    dashboard_auth_token: str = ""  # required to mutate; empty => controls refused

    # --- notifications / telegram (Phase 7) — offline fixture first; never trades ---
    telegram_enabled: bool = False
    telegram_transport: str = "fixture"  # fixture (offline) | http (deferred/off)
    telegram_allow_controls: bool = False  # inbound pause/halt only when true

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

    @model_validator(mode="after")
    def _validate_news_params(self) -> Settings:
        # NewsConfig.__post_init__ is the source-of-truth for invariants.
        self.news_config()
        return self

    @model_validator(mode="after")
    def _validate_ai_params(self) -> Settings:
        from app.ai.config import ModelClass

        # AIConfig.__post_init__ is the source-of-truth for invariants.
        self.ai_config()
        if self.ai_analyst_model_class not in {m.value for m in ModelClass}:
            raise ValueError(
                f"ai_analyst_model_class must be one of {[m.value for m in ModelClass]}, "
                f"got {self.ai_analyst_model_class!r}"
            )
        return self

    @model_validator(mode="after")
    def _validate_risk_params(self) -> Settings:
        # RiskConfig.__post_init__ is the source-of-truth for invariants.
        self.risk_config()
        return self

    @model_validator(mode="after")
    def _validate_paper_params(self) -> Settings:
        # PaperConfig.__post_init__ is the source-of-truth for invariants.
        self.paper_config()
        return self

    @model_validator(mode="after")
    def _validate_backtest_params(self) -> Settings:
        # BacktestConfig.__post_init__ is the source-of-truth for invariants;
        # building it here surfaces any violation as a fail-closed ConfigError.
        self.backtest_config()
        return self

    @model_validator(mode="after")
    def _validate_dashboard_params(self) -> Settings:
        from dashboard.config import DashboardConfig  # local import avoids cycle

        DashboardConfig(
            enabled=self.dashboard_enabled,
            host=self.dashboard_host,
            port=self.dashboard_port,
            auth_token=self.dashboard_auth_token,
        )
        return self

    @model_validator(mode="after")
    def _validate_notifications_params(self) -> Settings:
        # NotificationsConfig.__post_init__ is the source-of-truth for invariants.
        self.notifications_config()
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

    def news_config(self) -> NewsConfig:
        from app.news.config import NewsConfig

        return NewsConfig(
            max_news_age=timedelta(seconds=self.news_max_age_seconds),
            dedup_window=timedelta(seconds=self.news_dedup_window_seconds),
            require_known_availability=self.news_require_known_availability,
            known_assets=tuple(self.news_known_assets),
        )

    def ai_config(self) -> AIConfig:
        from app.ai.config import AIConfig, ModelClass

        return AIConfig(
            analyst_model_class=ModelClass(self.ai_analyst_model_class),
            haiku_model_id=self.ai_haiku_model_id,
            sonnet_model_id=self.ai_sonnet_model_id,
            opus_model_id=self.ai_opus_model_id,
            analyst_enabled=self.ai_analyst_enabled,
            timeout_seconds=self.ai_timeout_seconds,
            uncertain_policy=self.ai_uncertain_policy,
        )

    def risk_config(self) -> RiskConfig:
        from app.risk.config import RiskConfig

        return RiskConfig(
            max_risk_per_trade_pct=self.risk_max_risk_per_trade_pct,
            max_single_asset_exposure_pct=self.risk_max_single_asset_exposure_pct,
            max_total_exposure_pct=self.risk_max_total_exposure_pct,
            max_simultaneous_positions=self.risk_max_simultaneous_positions,
            correlated_exposure_cap_pct=self.risk_correlated_exposure_cap_pct,
            max_daily_loss_pct=self.risk_max_daily_loss_pct,
            max_weekly_loss_pct=self.risk_max_weekly_loss_pct,
            max_drawdown_pct=self.risk_max_drawdown_pct,
            vol_shock_atr_pct=self.risk_vol_shock_atr_pct,
            abnormal_spread_pct=self.risk_abnormal_spread_pct,
            abnormal_slippage_pct=self.risk_abnormal_slippage_pct,
            max_staleness_intervals=self.risk_max_staleness_intervals,
        )

    def paper_config(self) -> PaperConfig:
        from app.execution.config import PaperConfig

        return PaperConfig(
            taker_fee_pct=self.cost_taker_fee_pct,
            tick_size=self.sizing_tick_size,
            step_size=self.sizing_step_size,
            min_notional=self.sizing_min_notional,
            liquidity_fill_cap=self.paper_liquidity_fill_cap,
            starting_equity=self.paper_starting_equity,
        )

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

    def backtest_config(self) -> BacktestConfig:
        from app.costs.config import CostScenario
        from backtesting.config import BacktestConfig, EntryFillRule, HaltPolicy
        from backtesting.config import BacktestConfig as _BC  # noqa: F401

        return BacktestConfig(
            dataset_name=self.backtest_dataset_name,
            starting_equity=self.backtest_starting_equity,
            cost_scenario=CostScenario(self.backtest_cost_scenario),
            seed=self.backtest_seed,
            halt_policy=HaltPolicy(self.backtest_halt_policy),
            entry_fill_rule=EntryFillRule(self.backtest_entry_fill_rule),
            min_operational_trades=self.backtest_min_operational_trades,
            artifacts_dir=self.backtest_artifacts_dir,
        )

    def notifications_config(self) -> NotificationsConfig:
        from app.notifications.config import NotificationsConfig, NotificationTransportKind

        return NotificationsConfig(
            enabled=self.telegram_enabled,
            transport=NotificationTransportKind(self.telegram_transport),
            allow_controls=self.telegram_allow_controls,
            bot_token=self.telegram_bot_token,
            chat_id=self.telegram_chat_id,
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
            self.dashboard_auth_token,
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
