"""H9: persistence failure → HALT (independent session), atomic rollback, restart."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.database import session_scope
from app.engine.pipeline import TickOutcome
from app.models import PaperOrderRecord, PositionRecord
from app.risk.kill_switch import KillSwitch, KillSwitchStatus
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


def test_persistence_failure_halts_atomically_and_survives_restart(tmp_path) -> None:
    sf = make_session_factory_tmp(tmp_path)
    eng = build_engine(sf, approve_settings(), analyst_response=APPROVE)

    def boom(**kwargs):
        raise RuntimeError("database unavailable")

    eng._rec.record_tick = boom  # simulate a persistence failure mid-tick

    with pytest.raises(RuntimeError):
        eng.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)

    # HALT was written in an independent session (never lost with the rollback)
    assert KillSwitch(sf).current().status is KillSwitchStatus.HALTED
    # atomic: no partial trading state committed
    assert _count(sf, PaperOrderRecord) == 0
    assert _count(sf, PositionRecord) == 0

    # restart: a fresh engine over the same DB stays halted and executes nothing
    eng2 = build_engine(sf, approve_settings(), analyst_response=APPROVE)
    r = eng2.process_tick(decision_time=DT, now=DT, symbol=SYMBOL)
    assert r.outcome is TickOutcome.KILL_HALTED
    assert _count(sf, PositionRecord) == 0
