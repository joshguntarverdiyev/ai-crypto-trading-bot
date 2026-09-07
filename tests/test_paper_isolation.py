"""P9 per-run database isolation, run-identity invariant, ownership."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.database import session_scope
from app.exceptions import PaperRunError
from app.models import PaperDecisionRecord, PaperOrderRecord, PaperTradingRunRecord, PositionRecord
from app.paper.store import (
    acquire_run_lock,
    assert_run_identity,
    make_run_session_factory,
    resume_paper_run,
)
from app.time_utils import utc_now
from tests._p6_helpers import build_1h_raw_with_crash, decision_now
from tests._p9_helpers import build_paper, main_factory, paper_settings


def _count(sf, model) -> int:
    with session_scope(sf) as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


def test_two_runs_same_boundary_apply_independently(tmp_path) -> None:
    """Same (decision_time, symbol) in two runs both execute — separate DB files
    ⇒ disjoint intent_id namespaces ⇒ NO false duplicate_intent across runs."""
    s = paper_settings(tmp_path)
    main_sf = main_factory(s)
    r1, id1, _, _ = build_paper(tmp_path, raw_1h=build_1h_raw_with_crash(),
                                settings=s, main_sf=main_sf)
    r2, id2, _, _ = build_paper(tmp_path, raw_1h=build_1h_raw_with_crash(),
                                settings=s, main_sf=main_sf)
    assert id1 != id2

    out1 = r1.run_once(decision_now())
    out2 = r2.run_once(decision_now())
    assert out1[0].outcome.value == "trade"
    assert out2[0].outcome.value == "trade"  # run B applied its own ledger (not deduped vs A)

    cfg = s.paper_validation_config()
    sf1 = make_run_session_factory(cfg, id1, create=False)
    sf2 = make_run_session_factory(cfg, id2, create=False)
    assert _count(sf1, PaperOrderRecord) == 1
    assert _count(sf2, PaperOrderRecord) == 1
    assert _count(sf1, PositionRecord) == 1
    assert _count(sf2, PositionRecord) == 1
    # run-identity stamped correctly + physically separate files
    with session_scope(sf2) as sess:
        d = sess.scalars(select(PaperDecisionRecord)).first()
        assert d.paper_run_id == id2
    assert Path(cfg.paper_runs_dir, id1 + ".db").exists()
    assert Path(cfg.paper_runs_dir, id2 + ".db").exists()


def test_resume_unknown_run_fails_closed(tmp_path) -> None:
    s = paper_settings(tmp_path)
    main_sf = main_factory(s)
    with pytest.raises(PaperRunError):
        resume_paper_run(main_sf, s.paper_validation_config(), "does-not-exist",
                         owner_token="t")


def test_missing_run_db_never_recreated(tmp_path) -> None:
    s = paper_settings(tmp_path)
    cfg = s.paper_validation_config()
    with pytest.raises(PaperRunError):
        make_run_session_factory(cfg, "ghost-run", create=False)


def test_run_identity_mismatch_fails_closed(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path, raw_1h=build_1h_raw_with_crash())
    runner.run_once(decision_now())  # writes paper_decisions with paper_run_id == run_id
    cfg = settings.paper_validation_config()
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    with pytest.raises(PaperRunError):
        assert_run_identity(run_sf, "some-other-run-id")


def test_ownership_lock_blocks_second_process(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path)  # holds the lock
    cfg = settings.paper_validation_config()
    with pytest.raises(PaperRunError):
        acquire_run_lock(cfg, run_id)  # second acquisition of the same run is refused


def test_takeover_only_when_heartbeat_stale(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path)
    cfg = settings.paper_validation_config()
    # Release the live lock (simulate crash) but heartbeat is still fresh → refuse.
    from app.paper.store import release_run_lock
    release_run_lock(runner._lock)
    with pytest.raises(PaperRunError):
        resume_paper_run(main_sf, cfg, run_id, owner_token="new-owner")
    # Age the heartbeat beyond staleness → takeover allowed.
    from datetime import timedelta
    with session_scope(main_sf) as s:
        row = s.get(PaperTradingRunRecord, run_id)
        row.heartbeat_at = utc_now() - timedelta(
            seconds=cfg.owner_stale_intervals * cfg.primary_timeframe.seconds + 3600
        )
    run_sf, took_over = resume_paper_run(main_sf, cfg, run_id, owner_token="new-owner")
    assert took_over is True
