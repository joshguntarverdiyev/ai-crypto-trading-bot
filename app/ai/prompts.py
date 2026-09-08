"""Versioned, deterministic analyst prompt builder (Phase 5).

Pure function of (candidate + news context) → prompt text, tagged with
``PROMPT_VERSION``. Contains ONLY market/news facts — never credentials,
configuration, or environment (Master Plan §17). The prompt asks the analyst for
the strict structured JSON validated by ``app.ai.schema``.
"""

from __future__ import annotations

from app.ai.config import PROMPT_VERSION
from app.ai.models import AnalystDecision, EventRisk, ReasonCode
from app.news.models import NewsContext
from app.strategy.models import Candidate

# Derive the allowed vocabulary from the enums so the prompt can NEVER drift from
# the strict schema validator (app/ai/schema.py). The model is constrained to these
# exact values; anything else is rejected → HOLD (fail-closed, never weakened).
_DECISIONS = "|".join(d.value for d in AnalystDecision)
_EVENT_RISKS = "|".join(e.value for e in EventRisk)
_REASON_CODES = ", ".join(r.value for r in ReasonCode)


def build_analyst_prompt(candidate: Candidate, news: NewsContext) -> str:
    lines: list[str] = [
        f"PROMPT_VERSION={PROMPT_VERSION}",
        "ROLE: advisory risk analyst. You cannot place orders or change risk"
        " limits. Return ONLY the required JSON.",
        "",
        "CANDIDATE:",
        f"  direction={candidate.direction.value}",
        f"  symbol={candidate.symbol}",
        f"  timeframe={candidate.timeframe.value}",
        f"  close_time={candidate.close_time.isoformat()}",
        f"  entry_ref={candidate.entry_ref}",
        f"  stop_price={candidate.stop_price}",
        f"  target_price={candidate.target_price}",
        f"  expected_gross_move_pct={candidate.expected_gross_move_pct}",
        f"  reward_risk={candidate.reward_risk}",
        f"  atr_pct={candidate.atr_pct}",
        f"  confirmed_4h={candidate.confirmed_4h}",
        "",
        f"NEWS (availability={news.availability.value},"
        f" decision_time={news.decision_time.isoformat()}):",
    ]
    if news.items:
        for item in news.items:
            assets = ",".join(item.affected_assets) or "-"
            lines.append(
                f"  - [{item.source}] {item.title} "
                f"(available_at={item.available_at.isoformat()}, assets={assets})"
            )
    else:
        lines.append("  (no usable news items)")
    lines += [
        "",
        "OUTPUT CONTRACT — return ONE JSON object and NOTHING else. No markdown, no"
        " code fences (no ```), no prose, no comments. Exact keys and value formats:",
        f'  "decision": one of [{_DECISIONS}]',
        '  "confidence": number in 0..1',
        f"  \"reason_codes\": array using ONLY these values [{_REASON_CODES}];"
        ' use [] if none, or ["unknown"] if unsure. Do NOT invent codes.',
        '  "affected_assets": array of BASE asset symbols only, UPPERCASE'
        ' alphanumeric, NO quote/pair and NO slash (e.g. "BTC", not "BTC/USDT"); [] if none.',
        f'  "event_risk": one of [{_EVENT_RISKS}]',
        '  "evidence": array of short plain strings (never objects).',
    ]
    return "\n".join(lines)
