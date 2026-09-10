"""Google Gemini analyst provider — offline, fail-closed, schema-parity with Claude.

No network and no ``google-genai`` install: the SDK is faked via ``sys.modules`` so
these tests exercise the provider's control flow, JSON-mode request, failure mapping,
and (through the UNCHANGED ``ClaudeAnalyst`` + validator) the exact same analyst schema
and fail-closed HOLD behavior as the Anthropic path. The Anthropic path is asserted
unchanged.
"""

from __future__ import annotations

import sys
import types as _t

import pytest

from app.ai.analyst import ClaudeAnalyst
from app.ai.config import AIConfig, ModelClass
from app.ai.gemini_provider import GeminiAnalystProvider
from app.ai.models import AnalystAction, AnalystDecision, AnalystFailure
from app.ai.provider import AnalystRequest
from app.config import load_settings
from app.exceptions import AITimeoutError, AIUnavailableError, ConfigError
from tests._p5_helpers import DT, available_news, candidate, response


class _FakeDeadlineTimeout(Exception):  # class name contains "timeout" → AITimeoutError
    """Stand-in for a google-genai deadline/timeout exception."""


def _install_fake_genai(monkeypatch, *, text="{}", gen_exc=None, client_exc=None):
    captured: dict[str, object] = {}

    class HttpOptions:
        def __init__(self, **kw):
            captured["http_options"] = kw

    class GenerateContentConfig:
        def __init__(self, **kw):
            captured["config"] = kw

    class _Models:
        def generate_content(self, **kw):
            captured["call"] = kw
            if gen_exc is not None:
                raise gen_exc
            return _t.SimpleNamespace(text=text)

    class _Client:
        def __init__(self, **kw):
            captured["client"] = kw
            if client_exc is not None:
                raise client_exc
            self.models = _Models()

    gtypes = _t.ModuleType("google.genai.types")
    gtypes.HttpOptions = HttpOptions
    gtypes.GenerateContentConfig = GenerateContentConfig
    genai = _t.ModuleType("google.genai")
    genai.Client = _Client
    genai.types = gtypes
    google = _t.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)
    return captured


def _req(prompt="PROMPT", model="gemini-3.6-flash", timeout=20.0) -> AnalystRequest:
    return AnalystRequest(prompt=prompt, model_id=model, model_class="gemini_flash",
                          prompt_version="analyst-v2", timeout_seconds=timeout)


# --- provider mechanics --------------------------------------------------------------
def test_analyze_returns_text_and_uses_json_mode(monkeypatch) -> None:
    cap = _install_fake_genai(monkeypatch, text='{"decision":"approve"}')
    out = GeminiAnalystProvider(api_key="k").analyze(_req(prompt="P", model="gemini-3.6-flash"))
    assert out == '{"decision":"approve"}'
    assert cap["config"]["response_mime_type"] == "application/json"  # JSON mode requested
    assert cap["config"]["max_output_tokens"] == 1024
    assert cap["call"]["model"] == "gemini-3.6-flash"                 # runtime-resolved id
    assert cap["call"]["contents"] == "P"                            # exact prompt, no mutation
    assert cap["http_options"]["timeout"] == 20000                   # seconds → ms


def test_empty_api_key_raises() -> None:
    with pytest.raises(ValueError, match="non-empty api_key"):
        GeminiAnalystProvider(api_key="")


def test_timeout_maps_to_ai_timeout(monkeypatch) -> None:
    _install_fake_genai(monkeypatch, gen_exc=_FakeDeadlineTimeout("slow"))
    with pytest.raises(AITimeoutError):
        GeminiAnalystProvider(api_key="k").analyze(_req())


def test_generic_error_maps_to_unavailable(monkeypatch) -> None:
    _install_fake_genai(monkeypatch, gen_exc=ValueError("boom"))
    with pytest.raises(AIUnavailableError):
        GeminiAnalystProvider(api_key="k").analyze(_req())


def test_client_construction_failure_maps_to_unavailable(monkeypatch) -> None:
    _install_fake_genai(monkeypatch, client_exc=RuntimeError("no client"))
    with pytest.raises(AIUnavailableError):
        GeminiAnalystProvider(api_key="k").analyze(_req())


def test_missing_sdk_maps_to_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "google.genai", None)  # force ImportError on lazy import
    with pytest.raises(AIUnavailableError, match="google-genai is not installed"):
        GeminiAnalystProvider(api_key="k").analyze(_req())


def test_empty_response_text_returns_empty(monkeypatch) -> None:
    _install_fake_genai(monkeypatch, text=None)  # blocked/empty → "" → SCHEMA_INVALID upstream
    assert GeminiAnalystProvider(api_key="k").analyze(_req()) == ""


# --- schema parity + fail-closed through the UNCHANGED ClaudeAnalyst ------------------
def _analyst() -> ClaudeAnalyst:
    return ClaudeAnalyst(AIConfig(analyst_model_class=ModelClass.GEMINI_FLASH),
                         GeminiAnalystProvider(api_key="k"))


def test_gemini_approve_proceeds_with_correct_audit(monkeypatch) -> None:
    _install_fake_genai(monkeypatch, text=response("approve", reason_codes=["event_risk"]))
    v = _analyst().analyze(candidate(), available_news(), decision_time=DT)
    assert v.action is AnalystAction.PROCEED and v.decision is AnalystDecision.APPROVE
    assert v.failure is AnalystFailure.OK
    assert v.model_id == "gemini-3.6-flash" and v.model_class == "gemini_flash"


def test_gemini_veto_holds(monkeypatch) -> None:
    _install_fake_genai(monkeypatch, text=response("veto"))
    v = _analyst().analyze(candidate(), available_news(), decision_time=DT)
    assert v.action is AnalystAction.HOLD and v.decision is AnalystDecision.VETO


def test_gemini_invalid_json_holds_schema_invalid(monkeypatch) -> None:
    _install_fake_genai(monkeypatch, text="{ not json")
    v = _analyst().analyze(candidate(), available_news(), decision_time=DT)
    assert v.action is AnalystAction.HOLD and v.failure is AnalystFailure.SCHEMA_INVALID


def test_gemini_provider_failure_holds(monkeypatch) -> None:
    _install_fake_genai(monkeypatch, gen_exc=ValueError("boom"))
    v = _analyst().analyze(candidate(), available_news(), decision_time=DT)
    assert v.action is AnalystAction.HOLD and v.failure is AnalystFailure.UNAVAILABLE


# --- config resolution ---------------------------------------------------------------
def test_ai_config_resolves_gemini_model_id() -> None:
    gflash = AIConfig(analyst_model_class=ModelClass.GEMINI_FLASH)
    assert gflash.analyst_model_id == "gemini-3.6-flash"
    assert AIConfig(
        analyst_model_class=ModelClass.GEMINI_FLASH, gemini_model_id="gemini-3.6-flash-lite"
    ).analyst_model_id == "gemini-3.6-flash-lite"
    assert AIConfig().analyst_model_id == "claude-sonnet-4-6"  # default (Claude) unchanged


# --- settings fail-closed guard ------------------------------------------------------
def test_settings_gemini_valid_combo_loads() -> None:
    s = load_settings(_env_file=None, ai_provider="gemini",
                      ai_analyst_model_class="gemini_flash", google_api_key="k")
    assert s.ai_config().analyst_model_id == "gemini-3.6-flash"


def test_settings_gemini_provider_wrong_class_fails() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, ai_provider="gemini",
                      ai_analyst_model_class="sonnet", google_api_key="k")


def test_settings_gemini_class_wrong_provider_fails() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, ai_provider="anthropic",
                      ai_analyst_model_class="gemini_flash")


def test_settings_gemini_requires_key() -> None:
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, ai_provider="gemini", ai_analyst_model_class="gemini_flash")


# --- provider selection (build) — Gemini selected; Anthropic path unchanged ----------
def test_build_selects_gemini_provider() -> None:
    from app.paper.build import _analyst_provider

    s = load_settings(_env_file=None, ai_provider="gemini",
                      ai_analyst_model_class="gemini_flash", google_api_key="k")
    p = _analyst_provider(s, s.paper_validation_config())
    assert isinstance(p, GeminiAnalystProvider)


def test_build_anthropic_path_unchanged() -> None:
    from app.ai.anthropic_provider import AnthropicAnalystProvider
    from app.paper.build import _analyst_provider

    s = load_settings(_env_file=None, ai_provider="anthropic", anthropic_api_key="k")
    p = _analyst_provider(s, s.paper_validation_config())
    assert isinstance(p, AnthropicAnalystProvider)
