"""Strict validation of the raw analyst response (Phase 5).

Deterministic. Parses the model's JSON text into a ``ParsedAnalystResponse`` or
returns ``None`` on ANY violation (unparseable, missing key, bad enum,
out-of-range confidence, wrong types) — invalid Claude output must map to HOLD
(Master Plan §6). The model's self-reported identity is deliberately ignored:
the authoritative ``model_id`` / ``prompt_version`` are stamped by the analyst
from versioned config, so the model cannot misreport what audited it.

Envelope tolerance (P9 preflight fix): a model may return the SAME strict JSON
wrapped in a harmless envelope — a Markdown code fence (```json ... ```) or a
short preamble/trailer around the object. That envelope is stripped
DETERMINISTICALLY before parsing, but the strict object validation below is
UNCHANGED: the extracted object must still satisfy every key/enum/type/range
rule, and any malformed/ambiguous content still yields ``None`` → HOLD. No field
is ever inferred; this only removes formatting, never relaxes the schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.ai.models import AnalystDecision, EventRisk, ReasonCode

_REQUIRED_KEYS = frozenset(
    {"decision", "confidence", "reason_codes", "affected_assets", "event_risk", "evidence"}
)


def _json_candidates(raw: str) -> list[str]:
    """Deterministic candidate JSON strings to try, in order: the raw text as-is
    (unchanged behavior for already-clean JSON), then the same text with a Markdown
    code fence removed, then the outermost ``{...}`` slice (prose around one object).
    Every candidate is still subject to the full strict validation below."""
    cands: list[str] = [raw]
    s = raw.strip()
    if s.startswith("```"):
        body = s[3:]
        newline = body.find("\n")
        if newline != -1:
            body = body[newline + 1:]  # drop an optional ```json language tag line
        end = body.rfind("```")
        if end != -1:
            body = body[:end]
        stripped = body.strip()
        if stripped:
            cands.append(stripped)
    left, right = s.find("{"), s.rfind("}")
    if left != -1 and right > left:
        cands.append(s[left: right + 1])
    return cands


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
    if not isinstance(raw, str):
        return None
    # Try each deterministic candidate; the FIRST that both parses AND passes the
    # unchanged strict validation wins. Envelope-only differences are recovered;
    # genuinely invalid content falls through to None (→ HOLD). Never permissive.
    for candidate in _json_candidates(raw):
        parsed = _validate_json_text(candidate)
        if parsed is not None:
            return parsed
    return None


def _validate_json_text(raw: str) -> ParsedAnalystResponse | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
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
