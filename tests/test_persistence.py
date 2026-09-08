"""P6 persistence: audit rows written; news idempotent; append-only fills."""

from __future__ import annotations

import json

from sqlalchemy import func, select

from app.database import session_scope
from app.models import (
    ClaudeDecisionRecord,
    NewsRecord,
    PaperFillRecord,
    PortfolioSnapshotRecord,
    RiskDecisionRecord,
)
from tests._p6_helpers import (
    SYMBOL,
    approve_settings,
    build_engine,
    decision_now,
    make_session_factory_tmp,
)

APPROVE = json.dumps({
    "decision": "approve", "confidence": 0.9, "reason_codes": [],
    "affected_assets": ["BTC"], "event_risk": "low", "evidence": ["ok"],
})
DT = decision_now()


def _count(sf, model) -> int:
    with session_scope(sf) as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


def test_approve_tick_writes_all_audit_rows(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    build_engine(sf, approve_settings(), analyst_response=APPROVE).process_tick(
        decision_time=DT, now=DT, symbol=SYMBOL
    )
    assert _count(sf, NewsRecord) == 1
    assert _count(sf, ClaudeDecisionRecord) == 1
    assert _count(sf, RiskDecisionRecord) == 1
    assert _count(sf, PaperFillRecord) == 1
    assert _count(sf, PortfolioSnapshotRecord) == 1


def test_claude_decision_denormalizes_model_identity(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    build_engine(sf, approve_settings(), analyst_response=APPROVE).process_tick(
        decision_time=DT, now=DT, symbol=SYMBOL
    )
    with session_scope(sf) as s:
        row = s.scalars(select(ClaudeDecisionRecord)).first()
        assert row is not None
        assert row.model_id == "claude-sonnet-4-6"  # exact runtime id (§16)
        assert row.prompt_version == "analyst-v2"


def test_news_is_idempotent_across_ticks(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(sf, approve_settings(), analyst_response=APPROVE)
    eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert _count(sf, NewsRecord) == 1  # (source, dedup_key) unique
