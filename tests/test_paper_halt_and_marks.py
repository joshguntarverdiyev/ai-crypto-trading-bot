"""P9 HALT protective exits (OD-1), DB-failure-during-HALT fail-safe, marks (OD-2)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from app.database import session_scope
from app.engine.pipeline import TradingEngine
from app.models import PaperOrderRecord, PositionRecord
from app.paper.store import make_run_session_factory
from tests._p6_helpers import (
    SYMBOL,
    approve_settings,
    build_1h_raw_with_crash,
    build_engine,
    decision_now,
    exit_decision_time,
    make_session_factory_tmp,
)
from tests._p9_helpers import APPROVE, build_paper


def _count(sf, model) -> int:
    with session_scope(sf) as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


# --- OD-2 marks: byte-identical default behavior ---------------------------
def test_marks_for_default_is_single_symbol() -> None:
    m = TradingEngine._marks_for(SYMBOL, Decimal("100"), None)
    assert m == {str(SYMBOL): Decimal("100")}


def test_marks_for_merges_and_overrides_current() -> None:
    marks = {"BTC/USDT": Decimal("1"), "ETH/USDT": Decimal("2")}
    m = TradingEngine._marks_for(SYMBOL, Decimal("100"), marks)
    assert m["ETH/USDT"] == Decimal("2")
    assert m["BTC/USDT"] == Decimal("100")  # own decision-time close takes precedence


def test_process_tick_marks_none_equivalent(tmp_path) -> None:
    sf1 = make_session_factory_tmp(tmp_path / "a")
    sf2 = make_session_factory_tmp(tmp_path / "b")
    e1 = build_engine(sf1, approve_settings(), analyst_response=APPROVE)
    e2 = build_engine(sf2, approve_settings(), analyst_response=APPROVE)
    dt = decision_now()
    r1 = e1.process_tick(decision_time=dt, now=dt, symbol=SYMBOL)
    r2 = e2.process_tick(decision_time=dt, now=dt, symbol=SYMBOL, marks=None)
    assert (r1.outcome, r1.stage, r1.reason) == (r2.outcome, r2.stage, r2.reason)
    assert _count(sf1, PositionRecord) == _count(sf2, PositionRecord) == 1


# --- OD-1 HALT protective exits --------------------------------------------
def test_halt_runs_protective_exit_no_new_entry(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    runner.run_once(decision_now())  # open a position
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    assert _count(run_sf, PositionRecord) == 1
    # HALT, then the exit boundary: protective exit must still fire (no new entry).
    runner._kill.halt("test_halt", exit_decision_time())
    out = runner.run_once(exit_decision_time())
    assert out[0].outcome.value == "exit"
    with session_scope(run_sf) as s:
        assert s.scalars(select(PositionRecord)).first().status == "closed"


def test_halt_with_no_position_creates_no_order(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path, analyst_response=APPROVE)
    runner._kill.halt("test_halt", decision_now())
    out = runner.run_once(decision_now())
    assert out[0].outcome.value == "hold"  # protective-exit path, no entry
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    assert _count(run_sf, PaperOrderRecord) == 0
    assert _count(run_sf, PositionRecord) == 0


def test_db_failure_during_halt_defers_exit_no_phantom(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, raw_1h=build_1h_raw_with_crash()
    )
    runner.run_once(decision_now())  # open a position
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    orders_before = _count(run_sf, PaperOrderRecord)
    # HALT + simulate DB unavailability at the protective-exit probe.
    runner._kill.halt("test_halt", exit_decision_time())
    runner._rec.db_healthy = lambda: False  # type: ignore[method-assign]
    out = runner.run_once(exit_decision_time())
    assert out == []  # deferred: no decision produced this boundary
    # No phantom exit: no new order, position still OPEN.
    assert _count(run_sf, PaperOrderRecord) == orders_before
    with session_scope(run_sf) as s:
        assert s.scalars(select(PositionRecord)).first().status == "open"
