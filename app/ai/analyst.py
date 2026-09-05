"""ClaudeAnalyst — the advisory veto orchestrator (Phase 5).

Deterministic control flow around a (possibly non-deterministic) provider:

    disabled / provider unavailable / timeout            → HOLD (UNAVAILABLE/TIMEOUT)
    news not AVAILABLE (§0.1-3)                           → HOLD (NEWS_UNAVAILABLE)
    invalid/unparseable response (§6)                     → HOLD (SCHEMA_INVALID)
    valid → APPROVE                                       → PROCEED
    valid → VETO / UNCERTAIN                              → HOLD

Every path returns an audit-complete ``AnalystVerdict`` stamped with the exact
runtime ``model_id`` (resolved from versioned config), ``model_class``, and
``prompt_version`` (§0.1-2 / §16). The analyst is strictly advisory: it holds no
credentials, places no orders, and never overrides risk limits — the RiskManager
(P6) is the final authority.
"""

from __future__ import annotations

from datetime import datetime

from app.ai.config import AI_ANALYST_VERSION, PROMPT_VERSION, AIConfig
from app.ai.models import (
    AnalystAction,
    AnalystDecision,
    AnalystFailure,
    AnalystVerdict,
)
from app.ai.prompts import build_analyst_prompt
from app.ai.provider import AnalystProvider, AnalystRequest
from app.ai.schema import validate_analyst_response
from app.exceptions import AITimeoutError, AIUnavailableError
from app.news.models import NewsAvailability, NewsContext
from app.strategy.models import Candidate
from app.time_utils import monotonic, utc_now


class ClaudeAnalyst:
    def __init__(
        self, config: AIConfig | None = None, provider: AnalystProvider | None = None
    ) -> None:
        self._cfg = config or AIConfig()
        self._provider = provider

    def _verdict(
        self,
        *,
        decision: AnalystDecision | None,
        action: AnalystAction,
        failure: AnalystFailure,
        decision_time: datetime,
        started: float,
        news: NewsContext | None,
        confidence: float | None = None,
        reason_codes: tuple = (),
        affected_assets: tuple = (),
        event_risk=None,
        evidence: tuple = (),
    ) -> AnalystVerdict:
        return AnalystVerdict(
            decision=decision,
            action=action,
            confidence=confidence,
            reason_codes=reason_codes,
            affected_assets=affected_assets,
            event_risk=event_risk,
            evidence=evidence,
            failure=failure,
            model_class=self._cfg.analyst_model_class.value,
            model_id=self._cfg.analyst_model_id,
            prompt_version=PROMPT_VERSION,
            ai_analyst_version=AI_ANALYST_VERSION,
            news_pipeline_version=news.news_pipeline_version if news else None,
            decision_time=decision_time,
            processed_at=utc_now(),
            latency_seconds=monotonic() - started,
        )

    def analyze(
        self, candidate: Candidate, news: NewsContext, *, decision_time: datetime
    ) -> AnalystVerdict:
        started = monotonic()

        def hold(failure: AnalystFailure) -> AnalystVerdict:
            return self._verdict(
                decision=None,
                action=AnalystAction.HOLD,
                failure=failure,
                decision_time=decision_time,
                started=started,
                news=news,
            )

        # Fail-safe gates (unknown state is never permissive).
        if not self._cfg.analyst_enabled or self._provider is None:
            return hold(AnalystFailure.UNAVAILABLE)
        if news.availability is not NewsAvailability.AVAILABLE:
            return hold(AnalystFailure.NEWS_UNAVAILABLE)

        request = AnalystRequest(
            prompt=build_analyst_prompt(candidate, news),
            model_id=self._cfg.analyst_model_id,
            model_class=self._cfg.analyst_model_class.value,
            prompt_version=PROMPT_VERSION,
            timeout_seconds=self._cfg.timeout_seconds,
        )
        try:
            raw = self._provider.analyze(request)
        except AITimeoutError:
            return hold(AnalystFailure.TIMEOUT)
        except AIUnavailableError:
            return hold(AnalystFailure.UNAVAILABLE)

        parsed = validate_analyst_response(raw)
        if parsed is None:
            return hold(AnalystFailure.SCHEMA_INVALID)

        # APPROVE → PROCEED; VETO / UNCERTAIN → HOLD (uncertain_policy="hold", §6).
        action = (
            AnalystAction.PROCEED
            if parsed.decision is AnalystDecision.APPROVE
            else AnalystAction.HOLD
        )
        return self._verdict(
            decision=parsed.decision,
            action=action,
            failure=AnalystFailure.OK,
            decision_time=decision_time,
            started=started,
            news=news,
            confidence=parsed.confidence,
            reason_codes=parsed.reason_codes,
            affected_assets=parsed.affected_assets,
            event_risk=parsed.event_risk,
            evidence=parsed.evidence,
        )
