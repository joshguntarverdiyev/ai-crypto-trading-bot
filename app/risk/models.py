"""RiskManager result + market-state types (Phase 6).

The RiskManager is the deterministic final authority: APPROVE (proceed to
execution) / HOLD (precautionary, no trade this tick, not an error) / REJECT (a
violation, logged). Claude is advisory only and can never relax a limit.

``MarketState`` is the explicit **injected** market snapshot (H8): spread/
slippage/volatility come from here (from a Phase 1 ``Ticker`` when present, else
the cost-model fallback; ATR% from P2 features). P6 invents no market observation
and implies no real order-book liquidity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.market_data.models import Symbol


class RiskDecision(StrEnum):
    APPROVE = "approve"
    HOLD = "hold"
    REJECT = "reject"


class RiskReason(StrEnum):
    OK = "ok"
    KILL_SWITCH_HALTED = "kill_switch_halted"
    KILL_SWITCH_PAUSED = "kill_switch_paused"
    MISSING_CANDIDATE = "missing_candidate"
    MISSING_PLAN = "missing_plan"
    ANALYST_NOT_PROCEED = "analyst_not_proceed"
    MARKET_STALE = "market_stale"
    MARKET_INVALID = "market_invalid"
    NON_FINITE = "non_finite"
    INCONSISTENT_PLAN = "inconsistent_plan"  # H6: recomputed risk diverges from plan
    EXCEEDS_PER_TRADE_RISK = "exceeds_per_trade_risk"
    EXCEEDS_SINGLE_ASSET = "exceeds_single_asset"
    EXCEEDS_TOTAL = "exceeds_total"
    EXCEEDS_CORRELATED = "exceeds_correlated"
    MAX_POSITIONS = "max_positions"
    INSUFFICIENT_CASH = "insufficient_cash"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    WEEKLY_LOSS_LIMIT = "weekly_loss_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    VOLATILITY_SHOCK = "volatility_shock"
    ABNORMAL_SPREAD = "abnormal_spread"
    ABNORMAL_SLIPPAGE = "abnormal_slippage"


@dataclass(frozen=True)
class MarketState:
    """Injected market snapshot for a decision (H8). No invented observations."""

    symbol: Symbol
    decision_time: datetime
    last_close: Decimal
    atr_pct: float | None
    spread_pct: float
    slippage_pct: float
    usable: bool  # Phase 1 series usability
    stale: bool


@dataclass(frozen=True)
class RiskAssessment:
    decision: RiskDecision
    reason: RiskReason
    symbol: Symbol | None
    recomputed_risk_pct: float | None
    exposure_after_pct: float | None
    evaluated: dict[str, str] = field(default_factory=dict)
    risk_version: str = ""
    config_version: str = ""
    decision_time: datetime | None = None
