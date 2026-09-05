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
