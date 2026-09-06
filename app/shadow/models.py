"""Shadow Mode in-process result types (Phase 8).

A ``ShadowResult`` is the outcome of ONE boundary for ONE symbol. It carries the
audit payloads the recorder persists (news items, the analyst verdict, the risk
assessment) plus a market/feature/regime summary and — on a would-be trade — the
HYPOTHETICAL order and (never-executed) fill. Nothing here is an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.ai.models import AnalystVerdict
from app.market_data.models import Symbol
from app.news.models import NewsItem
from app.risk.models import RiskAssessment


class ShadowOutcome(StrEnum):
    HOLD = "hold"  # pipeline ran; fail-closed no-trade (a real decision)
    REJECT = "reject"  # RiskManager REJECT (a real decision)
    WOULD_TRADE = "would_trade"  # APPROVE → hypothetical order computed (NOT executed)
    KILL_HALTED = "kill_halted"  # boundary skipped: kill switch HALTED
    KILL_PAUSED = "kill_paused"  # boundary skipped: kill switch PAUSED
    DATA_FAILURE = "data_failure"  # adapter/infra failure — NOT a decision row


@dataclass(frozen=True)
class ShadowResult:
    outcome: ShadowOutcome
    stage: str
    reason: str
    symbol: Symbol
    decision_time: datetime

    # Audit payloads (persisted by the recorder into the shared audit tables).
    news_items: tuple[NewsItem, ...] = ()
    verdict: AnalystVerdict | None = None
    risk_assessment: RiskAssessment | None = None

    # Summaries (denormalized onto the shadow_decisions row).
    regime: str | None = None
    market_summary: dict[str, str] = field(default_factory=dict)
    features_summary: dict[str, str] = field(default_factory=dict)

    # HYPOTHETICAL would-be order + (never-executed) fill — set only on WOULD_TRADE.
    hyp_side: str | None = None
    hyp_quantity: Decimal | None = None
    hyp_entry_ref: Decimal | None = None
    hyp_stop_price: Decimal | None = None
    hyp_target_price: Decimal | None = None
    hyp_fill_price: Decimal | None = None
    hyp_fill_fee: Decimal | None = None
    hyp_fill_state: str | None = None

    indicator_set_version: str = ""
    strategy_version: str = ""

    @property
    def persistable(self) -> bool:
        """A DATA_FAILURE is a gap (system_event), not a durable shadow decision."""
        return self.outcome is not ShadowOutcome.DATA_FAILURE
