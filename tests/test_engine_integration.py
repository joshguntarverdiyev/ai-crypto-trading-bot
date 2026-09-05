"""Full P4→P5→P6 tick integration: APPROVE/HOLD/REJECT, idempotency, restart."""

from __future__ import annotations

import json

from sqlalchemy import func, select

from app.database import session_scope
from app.engine.pipeline import TickOutcome
from app.models import PaperOrderRecord, PositionRecord
from app.risk.kill_switch import KillSwitch
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
VETO = json.dumps({
    "decision": "veto", "confidence": 0.9, "reason_codes": ["negative_high_impact_news"],
    "affected_assets": ["BTC"], "event_risk": "high", "evidence": ["bad"],
})
DT = decision_now()


def _count(sf, model) -> int:
    with session_scope(sf) as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


def test_approve_executes_and_persists(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(sf, approve_settings(), analyst_response=APPROVE)
    r = eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r.outcome is TickOutcome.TRADE
    assert _count(sf, PaperOrderRecord) == 1
    assert _count(sf, PositionRecord) == 1


def test_idempotent_no_duplicate_fill(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(sf, approve_settings(), analyst_response=APPROVE)
    eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    r2 = eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r2.reason == "duplicate_intent"
    assert _count(sf, PaperOrderRecord) == 1  # no second order/fill


def test_analyst_veto_holds(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(sf, approve_settings(), analyst_response=VETO)
    r = eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r.outcome is TickOutcome.HOLD and r.stage == "analyst"
    assert _count(sf, PositionRecord) == 0  # nothing executed


def test_news_unavailable_holds(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(sf, approve_settings(), analyst_response=APPROVE, news_available=False)
    r = eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r.outcome is TickOutcome.HOLD and r.stage == "analyst"
    assert r.reason == "news_unavailable"


def test_no_candidate_holds_without_4h(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    # require 4h confirmation but provide no 4h series → candidate HOLD
    eng = build_engine(
        sf, approve_settings(strategy_require_4h_confirmation=True), analyst_response=APPROVE
    )
    r = eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r.outcome is TickOutcome.HOLD and r.stage == "candidate"


def test_risk_reject_blocks_execution(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    # tiny single-asset cap → RiskManager REJECT even though candidate/analyst pass
    eng = build_engine(
        sf, approve_settings(risk_max_single_asset_exposure_pct=0.001), analyst_response=APPROVE
    )
    r = eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r.outcome is TickOutcome.REJECT and r.stage == "risk"
    assert _count(sf, PositionRecord) == 0


def test_kill_halt_blocks_tick(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    KillSwitch(sf).halt("manual", DT)
    eng = build_engine(sf, approve_settings(), analyst_response=APPROVE)
    r = eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r.outcome is TickOutcome.KILL_HALTED
    assert _count(sf, PositionRecord) == 0


def test_restart_recovery_rebuilds_and_stays_idempotent(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    settings = approve_settings()
    build_engine(sf, settings, analyst_response=APPROVE).process_tick(
        decision_time=DT, now=DT, symbol=SYMBOL
    )
    # "restart": brand-new engine instances over the same DB
    eng2 = build_engine(sf, settings, analyst_response=APPROVE)
    account = eng2._pf.load_account()  # rebuilt from DB
    assert account.open_count() == 1
    assert account.position_for(SYMBOL) is not None
    assert account.hwm_equity > 0
    r = eng2.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r.reason == "duplicate_intent"
    assert _count(sf, PaperOrderRecord) == 1


def test_determinism_identical_business_state(tmp_path) -> None:
    def run(name: str):
        d = tmp_path / name
        d.mkdir()
        sf = make_session_factory_tmp(d)
        build_engine(sf, approve_settings(), analyst_response=APPROVE).process_tick(
            decision_time=DT, now=DT, symbol=SYMBOL
        )
        acct = build_engine(sf, approve_settings(), analyst_response=APPROVE)._pf.load_account()
        return acct

    a, b = run("a"), run("b")
    assert a.cash == b.cash
    pa, pb = a.position_for(SYMBOL), b.position_for(SYMBOL)
    assert pa is not None and pb is not None
    assert (pa.quantity, pa.average_entry, pa.stop_price, pa.target_price) == (
        pb.quantity, pb.average_entry, pb.stop_price, pb.target_price,
    )
