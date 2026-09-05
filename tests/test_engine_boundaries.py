"""P6 corrective-pass integration tests: E43 decision idempotency, H58 look-ahead,
exit-risk boundary, HALT exit policy, and sticky (no auto-resume) pause."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.database import session_scope
from app.engine.pipeline import TickOutcome
from app.models import (
    ClaudeDecisionRecord,
    PaperOrderRecord,
    PositionRecord,
    RiskDecisionRecord,
)
from app.risk.kill_switch import KillSwitch, KillSwitchStatus
from tests._p6_helpers import (
    BASE,
    SYMBOL,
    approve_settings,
    build_1h_raw_with_crash,
    build_engine,
    decision_now,
    exit_decision_time,
    make_session_factory_tmp,
)

APPROVE = json.dumps({
    "decision": "approve", "confidence": 0.9, "reason_codes": [],
    "affected_assets": ["BTC"], "event_risk": "low", "evidence": ["ok"],
})
VETO = json.dumps({
    "decision": "veto", "confidence": 0.9, "reason_codes": ["negative_high_impact_news"],
    "affected_assets": ["BTC"], "event_risk": "high", "evidence": ["bad"],
})
DT = decision_now()


def _count(sf, model) -> int:
    with session_scope(sf) as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


# --- E43: decision idempotency on reprocessed non-executing ticks ----------

def test_hold_tick_does_not_duplicate_decisions(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(sf, approve_settings(), analyst_response=VETO)
    eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)  # reprocess same tick
    assert _count(sf, ClaudeDecisionRecord) == 1
    assert _count(sf, RiskDecisionRecord) == 0  # risk not reached on analyst veto


def test_reject_tick_does_not_duplicate_decisions(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(
        sf, approve_settings(risk_max_single_asset_exposure_pct=0.001), analyst_response=APPROVE
    )
    eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)  # reprocess
    assert _count(sf, ClaudeDecisionRecord) == 1
    assert _count(sf, RiskDecisionRecord) == 1
    assert _count(sf, PaperOrderRecord) == 0


# --- H58: look-ahead protection --------------------------------------------

def test_now_before_decision_time_fails_closed(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(sf, approve_settings(), analyst_response=APPROVE)
    r = eng.process_tick(decision_time=DT, now=DT - timedelta(hours=1), symbol=SYMBOL)
    assert r.outcome is TickOutcome.HOLD
    assert r.stage == "time_integrity"
    assert _count(sf, PositionRecord) == 0


def test_market_is_now_independent_and_causal(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(sf, approve_settings(), analyst_response=APPROVE)
    # candle index 238 closes at 239h (close 125); index 239 closes at 240h (124)
    m239, *_ = eng._market(SYMBOL, decision_time=BASE + timedelta(hours=239))
    m240, *_ = eng._market(SYMBOL, decision_time=BASE + timedelta(hours=240))
    assert m239.last_close == Decimal("125")  # candle 239 not yet closed → excluded
    assert m240.last_close == Decimal("124")  # one more candle only when decision_time reaches it
    # _market takes no `now`; identical decision_time → identical snapshot
    m239b, *_ = eng._market(SYMBOL, decision_time=BASE + timedelta(hours=239))
    assert m239b.last_close == m239.last_close


# --- Exit-risk boundary -----------------------------------------------------

def test_entry_cannot_reach_broker_without_approve(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(
        sf, approve_settings(risk_max_single_asset_exposure_pct=0.001), analyst_response=APPROVE
    )
    r = eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r.outcome is TickOutcome.REJECT
    assert _count(sf, PaperOrderRecord) == 0  # no order ever reached the broker/persist


def test_reduce_only_stop_exit_closes_position(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    settings = approve_settings()
    build_engine(sf, settings, analyst_response=APPROVE).process_tick(
        decision_time=DT, now=DT, symbol=SYMBOL
    )
    assert eng_open_count(sf, settings) == 1

    dt2 = exit_decision_time()
    eng2 = build_engine(
        sf, settings, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    r = eng2.process_tick(decision_time=dt2, now=dt2, symbol=SYMBOL)
    assert r.outcome is TickOutcome.EXIT
    assert eng2._pf.load_account().open_count() == 0  # closed; reduce-only
    with session_scope(sf) as s:
        sides = [o.side for o in s.scalars(select(PaperOrderRecord)).all()]
    assert "buy" in sides and "sell" in sides  # entry then reduce-only exit


# --- HALT exit policy (P6 paper: HALT freezes state, no exit processing) ----

def test_halt_freezes_exits(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    settings = approve_settings()
    build_engine(sf, settings, analyst_response=APPROVE).process_tick(
        decision_time=DT, now=DT, symbol=SYMBOL
    )
    KillSwitch(sf).halt("manual", DT)
    dt2 = exit_decision_time()
    eng2 = build_engine(
        sf, settings, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    r = eng2.process_tick(decision_time=dt2, now=dt2, symbol=SYMBOL)
    assert r.outcome is TickOutcome.KILL_HALTED
    assert eng2._pf.load_account().open_count() == 1  # position NOT exited during HALT
    with session_scope(sf) as s:
        sides = [o.side for o in s.scalars(select(PaperOrderRecord)).all()]
    assert "sell" not in sides


# --- Auto-resume: pause is sticky (no automatic re-entry) -------------------

def test_pause_is_sticky_no_auto_resume(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    KillSwitch(sf).pause("abnormal_spread", DT)
    eng = build_engine(sf, approve_settings(), analyst_response=APPROVE)
    r1 = eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    r2 = eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r1.outcome is TickOutcome.KILL_PAUSED
    assert r2.outcome is TickOutcome.KILL_PAUSED  # still paused; no auto-resume
    assert KillSwitch(sf).current().status is KillSwitchStatus.PAUSED
    assert _count(sf, PositionRecord) == 0


def eng_open_count(sf, settings) -> int:
    return build_engine(sf, settings, analyst_response=APPROVE)._pf.load_account().open_count()
