"""Strategy result types (Phase 4).

Deterministic, descriptive outputs of the quant candidate generator. A
``Candidate`` is the artifact that later phases (P5 news/AI, P6 risk/paper)
consume; a ``SignalEvaluation`` records the per-candle decision (including HOLDs)
for auditability. Long-only (Master Plan §3).

Nothing here authorizes a trade. A candidate is a *proposal* that has passed the
deterministic reward:risk and cost gates only; the RiskManager (final authority)
is P6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.costs.models import EdgeAssessment
from app.market_data.models import Symbol, Timeframe


class SignalDirection(StrEnum):
    LONG = "long"  # spot, long-only (Master Plan §3) — no short/leverage


class SignalDecision(StrEnum):
    CANDIDATE = "candidate"
    HOLD = "hold"


class CandidateReason(StrEnum):
    OK = "ok"
    NOT_WARM = "not_warm"  # indicators not yet warm / required feature missing
    NON_FINITE = "non_finite"  # degenerate/non-finite numeric input → HOLD
    NO_TREND = "no_trend"  # 1h EMA50 not > EMA200 (no long up-trend)
    NO_4H_CONFIRMATION = "no_4h_confirmation"  # governing 4h absent/cold/disagrees
    NO_PULLBACK = "no_pullback"  # RSI above the pullback level
    RR_TOO_LOW = "rr_too_low"  # reward:risk below threshold
    COST_GATE_HOLD = "cost_gate_hold"  # P3 net-edge gate returned HOLD


@dataclass(frozen=True)
class Candidate:
    """A long candidate that passed the reward:risk and P3 cost gates.

    Advisory only — NOT an order and NOT authorization to trade. Prices/percentages
    are floats on the Phase 2 scale; money conversion happens at the sizing
    boundary. ``expected_gross_move_pct`` is a provisional model assumption
    (Contract clarification 1), not a prediction.
    """

    direction: SignalDirection
    source: str
    symbol: Symbol
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    entry_ref: float
    stop_price: float
    target_price: float
    risk_distance_pct: float
    expected_gross_move_pct: float
    reward_risk: float
    atr: float
    atr_pct: float
    confirmed_4h: bool
    governing_4h_open_time: datetime | None
    edge_assessment: EdgeAssessment
    strategy_version: str
    config_version: str


@dataclass(frozen=True)
class SignalEvaluation:
    """Per-candle decision. ``candidate`` is set iff ``decision`` is CANDIDATE."""

    source: str
    symbol: Symbol
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    decision: SignalDecision
    reason: CandidateReason
    candidate: Candidate | None
    strategy_version: str
    config_version: str


@dataclass(frozen=True)
class CandidateResult:
    evaluations: list[SignalEvaluation]
    strategy_version: str
    config_version: str

    @property
    def candidates(self) -> list[Candidate]:
        return [e.candidate for e in self.evaluations if e.candidate is not None]
