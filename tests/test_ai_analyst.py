"""ClaudeAnalyst state machine: APPROVE→PROCEED, everything else / failure → HOLD."""

from __future__ import annotations

from app.ai.analyst import ClaudeAnalyst
from app.ai.config import PROMPT_VERSION, AIConfig
from app.ai.fixture_provider import FixtureAnalystProvider
from app.ai.models import AnalystAction, AnalystDecision, AnalystFailure
from app.exceptions import AITimeoutError, AIUnavailableError
from tests._p5_helpers import DT, available_news, candidate, empty_news, response


def _analyst(provider: FixtureAnalystProvider | None, cfg: AIConfig | None = None) -> ClaudeAnalyst:
    return ClaudeAnalyst(cfg or AIConfig(), provider)


def test_approve_proceeds_and_is_audit_complete() -> None:
    a = _analyst(FixtureAnalystProvider(response("approve", reason_codes=["event_risk"])))
    v = a.analyze(candidate(), available_news(), decision_time=DT)
    assert v.decision is AnalystDecision.APPROVE
    assert v.action is AnalystAction.PROCEED
    assert v.failure is AnalystFailure.OK
    # audit-complete: exact runtime model id/class + prompt version recorded
    assert v.model_class == "sonnet"
    assert v.model_id == "claude-sonnet-4-6"
    assert v.prompt_version == PROMPT_VERSION
    assert v.news_pipeline_version == "news-v1"


def test_veto_holds() -> None:
    v = _analyst(FixtureAnalystProvider(response("veto"))).analyze(
        candidate(), available_news(), decision_time=DT
    )
    assert v.decision is AnalystDecision.VETO
    assert v.action is AnalystAction.HOLD


def test_uncertain_holds() -> None:
    v = _analyst(FixtureAnalystProvider(response("uncertain"))).analyze(
        candidate(), available_news(), decision_time=DT
    )
    assert v.decision is AnalystDecision.UNCERTAIN
    assert v.action is AnalystAction.HOLD


def test_invalid_output_holds_schema_invalid() -> None:
    v = _analyst(FixtureAnalystProvider("{not json")).analyze(
        candidate(), available_news(), decision_time=DT
    )
    assert v.action is AnalystAction.HOLD
    assert v.failure is AnalystFailure.SCHEMA_INVALID
    assert v.decision is None


def test_provider_unavailable_holds() -> None:
    v = _analyst(FixtureAnalystProvider(error=AIUnavailableError)).analyze(
        candidate(), available_news(), decision_time=DT
    )
    assert v.action is AnalystAction.HOLD
    assert v.failure is AnalystFailure.UNAVAILABLE


def test_provider_timeout_holds() -> None:
    v = _analyst(FixtureAnalystProvider(error=AITimeoutError)).analyze(
        candidate(), available_news(), decision_time=DT
    )
    assert v.action is AnalystAction.HOLD
    assert v.failure is AnalystFailure.TIMEOUT


def test_disabled_analyst_holds_without_calling_provider() -> None:
    provider = FixtureAnalystProvider(response("approve"))
    v = ClaudeAnalyst(AIConfig(analyst_enabled=False), provider).analyze(
        candidate(), available_news(), decision_time=DT
    )
    assert v.action is AnalystAction.HOLD
    assert v.failure is AnalystFailure.UNAVAILABLE
    assert provider.last_request is None  # provider never called


def test_missing_provider_holds() -> None:
    v = _analyst(None).analyze(candidate(), available_news(), decision_time=DT)
    assert v.action is AnalystAction.HOLD
    assert v.failure is AnalystFailure.UNAVAILABLE


def test_news_unavailable_holds_without_calling_provider() -> None:
    provider = FixtureAnalystProvider(response("approve"))
    v = _analyst(provider).analyze(candidate(), empty_news(), decision_time=DT)
    assert v.action is AnalystAction.HOLD
    assert v.failure is AnalystFailure.NEWS_UNAVAILABLE
    assert provider.last_request is None  # conservative: not consulted (§0.1-3)


def test_deterministic() -> None:
    a = _analyst(FixtureAnalystProvider(response("approve")))
    v1 = a.analyze(candidate(), available_news(), decision_time=DT)
    v2 = a.analyze(candidate(), available_news(), decision_time=DT)
    assert (v1.decision, v1.action, v1.model_id, v1.prompt_version) == (
        v2.decision, v2.action, v2.model_id, v2.prompt_version,
    )
