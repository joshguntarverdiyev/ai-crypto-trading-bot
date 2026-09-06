"""Phase 8 ShadowEngine pipeline tests — flat account, no execution (offline)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.exceptions import AIUnavailableError
from app.models import ShadowDecisionRecord
from app.risk.kill_switch import KillSwitchStatus
from app.shadow.models import ShadowOutcome
from tests import _p8_helpers as p8


def _run(session_factory, **kw):
    h = p8.build_shadow(session_factory, **kw)
    results = h.runner.run_once(p8.decision_now())
    return h, results


def test_approve_reaches_would_trade(db) -> None:
    _engine, sf, _url = db
    h, results = _run(sf)
    assert len(results) == 1
    r = results[0]
    assert r.outcome is ShadowOutcome.WOULD_TRADE
    assert r.hyp_side == "buy"
    assert r.hyp_quantity is not None and r.hyp_fill_price is not None
    assert r.regime is not None  # descriptive audit
    with sf() as s:
        row = s.scalars(select(ShadowDecisionRecord)).one()
        assert row.outcome == "would_trade"
        assert row.claude_decision_id and row.risk_decision_id
        assert row.hyp_fill_state == "filled"


def test_news_unavailable_holds(db) -> None:
    _engine, sf, _url = db
    _h, results = _run(sf, news_available=False)
    assert results[0].outcome is ShadowOutcome.HOLD
    assert results[0].stage == "analyst"
    assert results[0].reason == "news_unavailable"


def test_analyst_unavailable_holds(db) -> None:
    _engine, sf, _url = db
    _h, results = _run(sf, analyst_error=AIUnavailableError)
    assert results[0].outcome is ShadowOutcome.HOLD
    assert results[0].stage == "analyst"
    assert results[0].reason == "unavailable"


def test_schema_invalid_holds(db) -> None:
    _engine, sf, _url = db
    _h, results = _run(sf, analyst_response="{}")  # missing keys → schema_invalid → HOLD
    assert results[0].outcome is ShadowOutcome.HOLD
    assert results[0].reason == "schema_invalid"


def test_veto_holds(db) -> None:
    _engine, sf, _url = db
    veto = (
        '{"decision":"veto","confidence":0.9,"reason_codes":["event_risk"],'
        '"affected_assets":["BTC"],"event_risk":"high","evidence":["risk"]}'
    )
    _h, results = _run(sf, analyst_response=veto)
    assert results[0].outcome is ShadowOutcome.HOLD
    assert results[0].stage == "analyst"


def test_insufficient_history_fails_closed(db) -> None:
    # Warm-up min = IndicatorConfig.min_history(200) + buffer(100) = 300; supply < 300.
    _engine, sf, _url = db
    short = p8.build_1h_raw(n=250)
    h = p8.build_shadow(sf, raw_1h=short)
    results = h.runner.run_once(p8.decision_now(n=250))
    assert results[0].outcome is ShadowOutcome.HOLD
    assert results[0].stage == "warmup"
    assert results[0].reason == "insufficient_history"
    # No provider call (fail-closed before news/Claude); no would-be order.
    assert h.provider.last_request is None  # type: ignore[attr-defined]
    assert results[0].hyp_side is None


def test_sufficient_history_reaches_decision(db) -> None:
    _engine, sf, _url = db
    _h, results = _run(sf)  # N=360 >= 300
    assert results[0].outcome is not ShadowOutcome.HOLD or results[0].stage != "warmup"


def test_news_published_early_but_available_late_is_excluded(db) -> None:
    # §7.1: available_at > decision_time → excluded even though published_at <= dt.
    _engine, sf, _url = db
    dt = p8.decision_now()
    _h, results = _run(
        sf,
        news_published_at=dt - timedelta(hours=3),  # public before the boundary
        news_available_at=dt + timedelta(hours=1),  # but available only AFTER it
    )
    assert results[0].outcome is ShadowOutcome.HOLD
    assert results[0].stage == "analyst"
    assert results[0].reason == "news_unavailable"


def test_killswitch_halted_skips_pipeline(db) -> None:
    _engine, sf, _url = db
    h = p8.build_shadow(sf)
    h.kill_switch.halt("test", p8.decision_now())
    results = h.runner.run_once(p8.decision_now())
    assert results[0].outcome is ShadowOutcome.KILL_HALTED
    assert h.provider.last_request is None  # type: ignore[attr-defined]  # no external call
    assert h.kill_switch.current().status is KillSwitchStatus.HALTED


def test_killswitch_paused_skips_new_decision_no_exit_processing(db) -> None:
    # Flat account: PAUSED stops new decisions; there are no positions to exit.
    _engine, sf, _url = db
    h = p8.build_shadow(sf)
    h.kill_switch.pause("test", p8.decision_now())
    results = h.runner.run_once(p8.decision_now())
    assert results[0].outcome is ShadowOutcome.KILL_PAUSED
    from app.models import PaperFillRecord, PositionRecord
    with sf() as s:
        assert s.scalars(select(func.count()).select_from(PositionRecord)).one() == 0
        assert s.scalars(select(func.count()).select_from(PaperFillRecord)).one() == 0
