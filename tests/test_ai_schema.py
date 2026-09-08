"""Strict analyst-response schema validation (invalid → None → HOLD)."""

from __future__ import annotations

import json

from app.ai.models import AnalystDecision, EventRisk, ReasonCode
from app.ai.schema import validate_analyst_response


def _payload(**overrides) -> dict:
    base = {
        "decision": "approve",
        "confidence": 0.8,
        "reason_codes": ["event_risk"],
        "affected_assets": ["BTC"],
        "event_risk": "low",
        "evidence": ["ok"],
    }
    base.update(overrides)
    return base


def test_valid_response_parses() -> None:
    parsed = validate_analyst_response(json.dumps(_payload()))
    assert parsed is not None
    assert parsed.decision is AnalystDecision.APPROVE
    assert parsed.reason_codes == (ReasonCode.EVENT_RISK,)
    assert parsed.event_risk is EventRisk.LOW
    assert parsed.affected_assets == ("BTC",)


def test_unparseable_json_is_invalid() -> None:
    assert validate_analyst_response("{not valid") is None
    assert validate_analyst_response("[]") is None  # not an object


def test_missing_key_is_invalid() -> None:
    payload = _payload()
    del payload["event_risk"]
    assert validate_analyst_response(json.dumps(payload)) is None


def test_bad_enum_is_invalid() -> None:
    assert validate_analyst_response(json.dumps(_payload(decision="maybe"))) is None
    assert validate_analyst_response(json.dumps(_payload(event_risk="extreme"))) is None
    assert validate_analyst_response(json.dumps(_payload(reason_codes=["bogus"]))) is None


def test_confidence_out_of_range_or_wrong_type_is_invalid() -> None:
    assert validate_analyst_response(json.dumps(_payload(confidence=1.5))) is None
    assert validate_analyst_response(json.dumps(_payload(confidence=-0.1))) is None
    assert validate_analyst_response(json.dumps(_payload(confidence="high"))) is None
    assert validate_analyst_response(json.dumps(_payload(confidence=True))) is None


def test_bad_affected_assets_is_invalid() -> None:
    assert validate_analyst_response(json.dumps(_payload(affected_assets=["btc"]))) is None
    assert validate_analyst_response(json.dumps(_payload(affected_assets="BTC"))) is None
    assert validate_analyst_response(json.dumps(_payload(evidence="nope"))) is None


# --- P9 preflight: envelope tolerance (fences/prose) preserves fail-closed --------
def test_markdown_fenced_json_parses() -> None:
    body = json.dumps(_payload())
    fenced = f"```json\n{body}\n```"
    parsed = validate_analyst_response(fenced)
    assert parsed is not None and parsed.decision is AnalystDecision.APPROVE


def test_bare_fence_without_language_tag_parses() -> None:
    body = json.dumps(_payload(decision="veto", reason_codes=["negative_high_impact_news"]))
    parsed = validate_analyst_response(f"```\n{body}\n```")
    assert parsed is not None and parsed.decision is AnalystDecision.VETO


def test_prose_preamble_and_trailer_around_object_parses() -> None:
    body = json.dumps(_payload(decision="uncertain"))
    wrapped = f"Here is my analysis:\n{body}\nLet me know if you need more."
    parsed = validate_analyst_response(wrapped)
    assert parsed is not None and parsed.decision is AnalystDecision.UNCERTAIN


def test_fenced_but_semantically_invalid_still_holds() -> None:
    # envelope removed, but a bad enum value inside → still None → HOLD (not weakened)
    bad = json.dumps(_payload(event_risk="catastrophic"))
    assert validate_analyst_response(f"```json\n{bad}\n```") is None


def test_fenced_but_missing_key_still_holds() -> None:
    payload = _payload()
    del payload["confidence"]
    assert validate_analyst_response(f"```json\n{json.dumps(payload)}\n```") is None


def test_prose_with_no_json_object_is_invalid() -> None:
    assert validate_analyst_response("I cannot analyze this right now.") is None


def test_out_of_range_confidence_inside_fence_still_holds() -> None:
    bad = json.dumps(_payload(confidence=1.5))
    assert validate_analyst_response(f"```json\n{bad}\n```") is None


def test_non_upper_asset_inside_fence_still_holds() -> None:
    bad = json.dumps(_payload(affected_assets=["btc"]))  # not UPPER → HOLD
    assert validate_analyst_response(f"```json\n{bad}\n```") is None


def test_clean_json_behaviour_unchanged() -> None:
    # already-clean JSON parses via the first candidate (identical to prior behavior)
    parsed = validate_analyst_response(json.dumps(_payload()))
    assert parsed is not None
    # truly malformed (no object) still None
    assert validate_analyst_response("not json at all") is None
    assert validate_analyst_response("") is None


# --- P9 preflight: prompt constrains the model to the exact schema vocabulary ----
def test_prompt_enumerates_allowed_vocabulary_and_forbids_fences() -> None:
    from app.ai.models import ReasonCode
    from app.ai.prompts import build_analyst_prompt
    from tests._p5_helpers import available_news, candidate

    prompt = build_analyst_prompt(candidate(), available_news())
    # every allowed reason code is listed for the model
    for rc in ReasonCode:
        assert rc.value in prompt
    assert "no code fences" in prompt.lower() or "no ```" in prompt
    assert 'NO slash' in prompt or 'not "BTC/USDT"' in prompt  # base-asset instruction
    assert "short plain strings" in prompt  # evidence format
