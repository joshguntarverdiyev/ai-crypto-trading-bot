"""Claude/AI holds no credentials and never receives secrets (Master Plan §17)."""

from __future__ import annotations

from app.ai.analyst import ClaudeAnalyst
from app.ai.config import AIConfig
from app.ai.fixture_provider import FixtureAnalystProvider
from app.ai.prompts import build_analyst_prompt
from tests._p5_helpers import DT, available_news, candidate, response

SECRET = "sk-ant-SUPERSECRET-DO-NOT-LEAK"


def test_prompt_contains_only_market_news_facts() -> None:
    prompt = build_analyst_prompt(candidate(), available_news())
    assert SECRET not in prompt
    assert "api_key" not in prompt.lower()
    assert "BTC/USDT" in prompt  # market facts are present


def test_request_to_provider_carries_no_secret() -> None:
    provider = FixtureAnalystProvider(response("approve"))
    ClaudeAnalyst(AIConfig(), provider).analyze(candidate(), available_news(), decision_time=DT)
    assert provider.last_request is not None
    assert SECRET not in provider.last_request.prompt
    # the request exposes only a runtime-resolved model id, never a credential
    assert provider.last_request.model_id == "claude-sonnet-4-6"


def test_aiconfig_has_no_credential_field() -> None:
    fields = set(AIConfig().__dataclass_fields__)
    assert not any("key" in f or "secret" in f or "token" in f for f in fields)
