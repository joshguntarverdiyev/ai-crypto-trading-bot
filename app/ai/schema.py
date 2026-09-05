"""Strict validation of the raw analyst response (Phase 5).

Deterministic. Parses the model's JSON text into a ``ParsedAnalystResponse`` or
returns ``None`` on ANY violation (unparseable, missing key, bad enum,
out-of-range confidence, wrong types) — invalid Claude output must map to HOLD
(Master Plan §6). The model's self-reported identity is deliberately ignored:
the authoritative ``model_id`` / ``prompt_version`` are stamped by the analyst
from versioned config, so the model cannot misreport what audited it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.ai.models import AnalystDecision, EventRisk, ReasonCode

_REQUIRED_KEYS = frozenset(
    {"decision", "confidence", "reason_codes", "affected_assets", "event_risk", "evidence"}
)


@dataclass(frozen=True)
class ParsedAnalystResponse:
    decision: AnalystDecision
    confidence: float
    reason_codes: tuple[ReasonCode, ...]
    affected_assets: tuple[str, ...]
    event_risk: EventRisk
    evidence: tuple[str, ...]


def _str_list(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for element in value:
        if not isinstance(element, str):
            return None
        out.append(element)
    return out


def validate_analyst_response(raw: str) -> ParsedAnalystResponse | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if not _REQUIRED_KEYS.issubset(data.keys()):
        return None

    # decision / event_risk enums
    try:
        decision = AnalystDecision(data["decision"])
        event_risk = EventRisk(data["event_risk"])
    except ValueError:
        return None

    # confidence: real number in [0, 1] (bool is not accepted)
    confidence = data["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    confidence = float(confidence)
    if not (0.0 <= confidence <= 1.0):
        return None

    # reason_codes: list of valid enum members
    reason_raw = _str_list(data["reason_codes"])
    if reason_raw is None:
        return None
    try:
        reason_codes = tuple(ReasonCode(code) for code in reason_raw)
    except ValueError:
        return None

    # affected_assets: list of UPPER-alnum strings
    assets = _str_list(data["affected_assets"])
    if assets is None or any(not (a.isalnum() and a.isupper()) for a in assets):
        return None

    evidence = _str_list(data["evidence"])
    if evidence is None:
        return None

    return ParsedAnalystResponse(
        decision=decision,
        confidence=confidence,
        reason_codes=reason_codes,
        affected_assets=tuple(assets),
        event_risk=event_risk,
        evidence=tuple(evidence),
    )
