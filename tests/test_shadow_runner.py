"""Phase 8 ShadowRunner tests — timing, idempotency, gaps, failures (offline)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.exceptions import AdapterError
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.models import ShadowDecisionRecord, SystemEvent
from app.risk.kill_switch import KillSwitchState, KillSwitchStatus
from app.shadow.models import ShadowOutcome
from tests import _p8_helpers as p8


# --- timing ---------------------------------------------------------------
def test_boundary_is_floor_to_primary_timeframe(db) -> None:
    _e, sf, _u = db
    h = p8.build_shadow(sf)
    dt = p8.decision_now()
    assert h.runner.boundary(dt + timedelta(minutes=37)) == dt
    assert h.runner.boundary(dt) == dt


def test_now_before_decision_time_fails_closed(db) -> None:
    _e, sf, _u = db
    h = p8.build_shadow(sf)
    running = KillSwitchState(KillSwitchStatus.RUNNING, None, None)
    res = h.engine.process_boundary(
        decision_time=p8.decision_now(), now=p8.decision_now() - timedelta(hours=1),
        symbol=p8.SYMBOL, kill_state=running,
    )
    assert res.outcome is ShadowOutcome.HOLD
    assert res.stage == "time_integrity"


def test_multi_symbol_canonical_order(db) -> None:
    _e, sf, _u = db
    eth = p8.Symbol.parse("ETH/USDT")
    h = p8.build_shadow(sf, symbols=(eth, p8.SYMBOL))  # unsorted input
    results = h.runner.run_once(p8.decision_now())
    assert [str(r.symbol) for r in results] == ["BTC/USDT", "ETH/USDT"]


# --- idempotency / restart ------------------------------------------------
def test_idempotent_rerun_skips_before_provider_call(db) -> None:
    _e, sf, _u = db
    prov = p8.CountingProvider()
    h = p8.build_shadow(sf, provider=prov)
    h.runner.run_once(p8.decision_now())
    assert prov.calls == 1
    # Rerun the same boundary → skipped BEFORE any provider call.
    again = h.runner.run_once(p8.decision_now())
    assert again == []
    assert prov.calls == 1  # no duplicate Claude/news cost


def test_restart_resumes_without_reprocessing(db) -> None:
    _e, sf, _u = db
    h1 = p8.build_shadow(sf)
    h1.runner.run_once(p8.decision_now())
    # A fresh runner (simulated restart) on the same DB must not reprocess.
    h2 = p8.build_shadow(sf)
    assert h2.runner.run_once(p8.decision_now()) == []
    with sf() as s:
        assert s.scalars(select(func.count()).select_from(ShadowDecisionRecord)).one() == 1


# --- missed boundaries = gaps, not decisions ------------------------------
def test_missed_boundaries_recorded_as_gap_not_decisions(db) -> None:
    _e, sf, _u = db
    h = p8.build_shadow(sf)
    h.runner.run_once(p8.decision_now())  # boundary T0
    before = _count(sf, ShadowDecisionRecord)
    h.runner.run_once(p8.decision_now() + timedelta(hours=5))  # boundary T0+5 → 4 skipped
    gaps = _gap_events(sf)
    assert gaps, "expected a shadow.gap system event"
    assert gaps[-1]["skipped_boundaries"] == 4
    # The skipped boundaries did NOT create shadow decisions (only T0 and T0+5).
    assert _count(sf, ShadowDecisionRecord) == before + 1


# --- data failure policy --------------------------------------------------
class _FailingAdapter(FixtureExchangeAdapter):
    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):  # noqa: ANN001
        raise AdapterError("simulated exchange outage")


def test_data_failure_holds_boundary_no_decision_row(db) -> None:
    _e, sf, _u = db
    adapter = _FailingAdapter(symbols=[p8.SYMBOL], timeframes=[p8.Timeframe.H1, p8.Timeframe.H4])
    h = p8.build_shadow(sf, market_adapter=adapter)
    results = h.runner.run_once(p8.decision_now())
    assert results[0].outcome is ShadowOutcome.DATA_FAILURE
    assert _count(sf, ShadowDecisionRecord) == 0  # NOT a decision row
    assert any(e.message == "shadow.data_failure" for e in _events(sf))


def test_consecutive_data_failures_pause(db) -> None:
    _e, sf, _u = db
    adapter = _FailingAdapter(symbols=[p8.SYMBOL], timeframes=[p8.Timeframe.H1, p8.Timeframe.H4])
    h = p8.build_shadow(sf, market_adapter=adapter)  # default max=3
    for _ in range(3):
        h.runner.run_once(p8.decision_now())
    assert h.kill_switch.current().status is KillSwitchStatus.PAUSED


# --- persistence failure → HALT -------------------------------------------
def test_persistence_failure_halts(db, monkeypatch) -> None:
    _e, sf, _u = db
    h = p8.build_shadow(sf)

    def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(h.recorder, "record", boom)
    with pytest.raises(RuntimeError):
        h.runner.run_once(p8.decision_now())
    assert h.kill_switch.current().status is KillSwitchStatus.HALTED


# --- clock drift → PAUSE --------------------------------------------------
class _DriftAdapter(FixtureExchangeAdapter):
    def server_time_utc(self):  # noqa: ANN201
        return p8.decision_now() + timedelta(seconds=10_000)  # far from local `now`


def test_clock_drift_pauses(db) -> None:
    _e, sf, _u = db
    adapter = _DriftAdapter(
        ohlcv={("BTC/USDT", "1h"): p8.build_1h_raw(), ("BTC/USDT", "4h"): []},
        symbols=[p8.SYMBOL], timeframes=[p8.Timeframe.H1, p8.Timeframe.H4],
    )
    h = p8.build_shadow(sf, market_adapter=adapter)
    h.runner.run_once(p8.decision_now())
    assert h.kill_switch.current().status is KillSwitchStatus.PAUSED
    assert any(e.message == "shadow.clock_drift" for e in _events(sf))


# --- helpers --------------------------------------------------------------
def _count(sf, model) -> int:
    with sf() as s:
        return s.scalars(select(func.count()).select_from(model)).one()


def _events(sf):
    with sf() as s:
        return list(s.scalars(select(SystemEvent)).all())


def _gap_events(sf):
    import json

    out = []
    for e in _events(sf):
        if e.message == "shadow.gap":
            out.append(json.loads(e.context))
    return out
