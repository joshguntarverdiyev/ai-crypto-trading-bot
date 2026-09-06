"""Phase 8 external-call idempotency semantics (§10, offline).

* A durably-persisted boundary is skipped BEFORE any provider call (no duplicate
  Claude/news cost) — see also tests/test_shadow_runner.py.
* If an external call SUCCEEDS but the DB commit fails before durable persistence,
  a later restart MAY repeat the external call (at-least-once) — but it never
  yields a duplicate durable decision and never creates an execution path.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import (
    PaperFillRecord,
    PaperOrderRecord,
    PositionRecord,
    ShadowDecisionRecord,
)
from tests import _p8_helpers as p8


def test_commit_failure_then_restart_repeats_call_but_no_duplicate_or_execution(db) -> None:
    _e, sf, _u = db
    prov = p8.CountingProvider()
    h = p8.build_shadow(sf, provider=prov)

    original = h.recorder.record
    state = {"n": 0}

    def flaky_record(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("commit failed before durable persistence")
        return original(*args, **kwargs)

    h.recorder.record = flaky_record  # type: ignore[method-assign]

    # First attempt: external call succeeds, persistence fails → HALT, no durable row.
    try:
        h.runner.run_once(p8.decision_now())
    except RuntimeError:
        pass
    assert prov.calls == 1
    assert _count(sf, ShadowDecisionRecord) == 0

    # Restart: reset kill state and re-run the same boundary.
    from app.time_utils import utc_now
    h.kill_switch.manual_reset(utc_now())
    h.runner.run_once(p8.decision_now())

    # At-least-once: the external call was repeated...
    assert prov.calls == 2
    # ...but exactly ONE durable decision, and ZERO execution/operational rows.
    assert _count(sf, ShadowDecisionRecord) == 1
    for model in (PaperOrderRecord, PaperFillRecord, PositionRecord):
        assert _count(sf, model) == 0


def _count(sf, model) -> int:
    with sf() as s:
        return s.scalars(select(func.count()).select_from(model)).one()
