"""P9 Shadow↔Paper consistency: input-equivalence gating (no false drift)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.database import init_db, make_engine, make_session_factory, session_scope
from app.models import (
    ClaudeDecisionRecord,
    PaperDecisionRecord,
    RiskDecisionRecord,
    ShadowDecisionRecord,
)
from app.paper import consistency

DT = datetime(2026, 1, 11, 0, 0, tzinfo=UTC)
SYM = "BTC/USDT"


def _sf(path):
    e = make_engine(f"sqlite:///{path}")
    init_db(e)
    return make_session_factory(e)


def _claude(session, cid, *, model_id, action):
    session.add(ClaudeDecisionRecord(
        id=cid, decision_time=DT, symbol=SYM, decision="approve", action=action,
        confidence=0.9, reason_codes="[]", affected_assets="[]", event_risk="low",
        evidence="[]", failure="ok", model_class="sonnet", model_id=model_id,
        prompt_version="analyst-v1", ai_analyst_version="ai-v1", news_pipeline_version="news-v1",
        processed_at=DT, latency_seconds=0.1,
    ))


def _risk(session, rid, *, version, decision, reason, evaluated="{}"):
    session.add(RiskDecisionRecord(
        id=rid, decision_time=DT, symbol=SYM, decision=decision, reason=reason,
        reason_codes="[]", evaluated=evaluated, risk_version=version, config_version="cfg-1",
    ))


def test_only_paper_when_no_shadow(tmp_path) -> None:
    paper_sf = _sf(tmp_path / "run.db")
    shadow_sf = _sf(tmp_path / "shadow.db")
    with session_scope(paper_sf) as s:
        s.add(PaperDecisionRecord(
            paper_run_id="r1", decision_time=DT, symbol=SYM, outcome="hold",
            stage="candidate", reason="no_pullback", engine_version="paper-v1",
        ))
    rows = consistency.compare(shadow_sf, paper_sf)
    assert consistency.summarize(rows) == {"only_paper": 1}


def test_equal_inputs_equal_outputs_is_consistent(tmp_path) -> None:
    paper_sf = _sf(tmp_path / "run.db")
    shadow_sf = _sf(tmp_path / "shadow.db")
    with session_scope(paper_sf) as s:
        _claude(s, "c-p", model_id="claude-sonnet-4-6", action="proceed")
        _risk(s, "r-p", version="risk-v1", decision="approve", reason="ok")
        s.add(PaperDecisionRecord(
            paper_run_id="r1", decision_time=DT, symbol=SYM, outcome="trade",
            stage="execution", reason="filled", claude_decision_id="c-p",
            risk_decision_id="r-p", engine_version="paper-v1",
        ))
    with session_scope(shadow_sf) as s:
        _claude(s, "c-s", model_id="claude-sonnet-4-6", action="proceed")
        _risk(s, "r-s", version="risk-v1", decision="approve", reason="ok")
        s.add(ShadowDecisionRecord(
            decision_time=DT, symbol=SYM, outcome="would_trade", stage="execution",
            reason="filled", claude_decision_id="c-s", risk_decision_id="r-s",
            engine_version="shadow-v1",
        ))
    rows = consistency.compare(shadow_sf, paper_sf)
    assert consistency.summarize(rows) == {"consistent": 1}


def test_equal_inputs_different_outputs_is_drift(tmp_path) -> None:
    paper_sf = _sf(tmp_path / "run.db")
    shadow_sf = _sf(tmp_path / "shadow.db")
    with session_scope(paper_sf) as s:
        _claude(s, "c-p", model_id="claude-sonnet-4-6", action="proceed")
        _risk(s, "r-p", version="risk-v1", decision="approve", reason="ok")
        s.add(PaperDecisionRecord(
            paper_run_id="r1", decision_time=DT, symbol=SYM, outcome="trade",
            stage="execution", reason="filled", claude_decision_id="c-p",
            risk_decision_id="r-p", engine_version="paper-v1",
        ))
    with session_scope(shadow_sf) as s:
        _claude(s, "c-s", model_id="claude-sonnet-4-6", action="proceed")
        # same inputs (risk_version/config/evaluated) but DIFFERENT decision → drift
        _risk(s, "r-s", version="risk-v1", decision="reject", reason="max_positions")
        s.add(ShadowDecisionRecord(
            decision_time=DT, symbol=SYM, outcome="reject", stage="risk",
            reason="max_positions", claude_decision_id="c-s", risk_decision_id="r-s",
            engine_version="shadow-v1",
        ))
    rows = consistency.compare(shadow_sf, paper_sf)
    assert consistency.summarize(rows) == {"drift": 1}


def test_different_inputs_not_comparable(tmp_path) -> None:
    paper_sf = _sf(tmp_path / "run.db")
    shadow_sf = _sf(tmp_path / "shadow.db")
    with session_scope(paper_sf) as s:
        _claude(s, "c-p", model_id="claude-sonnet-4-6", action="proceed")
        _risk(s, "r-p", version="risk-v1", decision="approve", reason="ok", evaluated='{"a":1}')
        s.add(PaperDecisionRecord(
            paper_run_id="r1", decision_time=DT, symbol=SYM, outcome="trade",
            stage="execution", reason="filled", claude_decision_id="c-p",
            risk_decision_id="r-p", engine_version="paper-v1",
        ))
    with session_scope(shadow_sf) as s:
        _claude(s, "c-s", model_id="claude-sonnet-4-6", action="proceed")
        # different 'evaluated' snapshot ⇒ different external inputs ⇒ not_comparable
        _risk(s, "r-s", version="risk-v1", decision="reject", reason="max_positions",
              evaluated='{"a":2}')
        s.add(ShadowDecisionRecord(
            decision_time=DT, symbol=SYM, outcome="reject", stage="risk",
            reason="max_positions", claude_decision_id="c-s", risk_decision_id="r-s",
            engine_version="shadow-v1",
        ))
    rows = consistency.compare(shadow_sf, paper_sf)
    assert consistency.summarize(rows) == {"not_comparable": 1}
