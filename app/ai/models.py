"""AI-analyst result types (Phase 5).

The analyst is a strictly-advisory formal state machine (Master Plan §6). Its
structured decision is ``APPROVE | VETO | UNCERTAIN``; the deterministic pipeline
``action`` is ``PROCEED`` only on a clean APPROVE, otherwise ``HOLD``. Any failure
(invalid schema, provider unavailable/timeout, news unavailable) also → HOLD.

Claude never sees credentials, never places orders, and never overrides risk
limits — the RiskManager (P6) is the final authority. The verdict is
audit-complete: it records the exact runtime ``model_id``, ``model_class``, and
``prompt_version`` (§0.1-2 / §16).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AnalystDecision(StrEnum):
    APPROVE = "approve"
    VETO = "veto"
    UNCERTAIN = "uncertain"


class AnalystAction(StrEnum):
    PROCEED = "proceed"  # only on a clean APPROVE
    HOLD = "hold"


class ReasonCode(StrEnum):
    NEGATIVE_HIGH_IMPACT_NEWS = "negative_high_impact_news"
    EVENT_RISK = "event_risk"
    DATA_CONFLICT = "data_conflict"
    UNUSUAL_MARKET_CONDITION = "unusual_market_condition"
    LIQUIDITY_RISK = "liquidity_risk"
    SENTIMENT_CONFLICT = "sentiment_conflict"
    LOW_CONFIDENCE = "low_confidence"
    UNKNOWN = "unknown"


class EventRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AnalystFailure(StrEnum):
    OK = "ok"
    SCHEMA_INVALID = "schema_invalid"  # invalid/unparseable Claude output → HOLD
    UNAVAILABLE = "unavailable"  # provider unavailable / analyst disabled → HOLD
    TIMEOUT = "timeout"  # provider timed out → HOLD
    NEWS_UNAVAILABLE = "news_unavailable"  # news not AVAILABLE → conservative HOLD


@dataclass(frozen=True)
class AnalystVerdict:
    """Audit-complete, strictly-advisory analyst outcome."""

    decision: AnalystDecision | None  # None when a failure prevented a decision
    action: AnalystAction
    confidence: float | None
    reason_codes: tuple[ReasonCode, ...]
    affected_assets: tuple[str, ...]
    event_risk: EventRisk | None
    evidence: tuple[str, ...]
    failure: AnalystFailure
    model_class: str
    model_id: str  # exact runtime-resolved id (§0.1-2 / §16)
    prompt_version: str
    ai_analyst_version: str
    news_pipeline_version: str | None
    decision_time: datetime
    processed_at: datetime
    latency_seconds: float
