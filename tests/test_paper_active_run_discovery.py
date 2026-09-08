"""P9: resolve_active_run_id — read-only discovery of the UNIQUE active paper run.

Offline/deterministic. Discovery returns a run_id ONLY when exactly one catalog row is
status='running' with a fresh heartbeat; anything else (none, stopped, stale, ambiguous)
returns None so callers fail closed.
"""

from __future__ import annotations

from datetime import timedelta

from app.database import session_scope
from app.models import PaperTradingRunRecord
from app.paper.store import resolve_active_run_id
from app.time_utils import utc_now
from tests._p9_helpers import build_paper, main_factory, paper_settings

STALE = timedelta(days=100)  # far beyond any owner_stale_intervals window


def _patch_catalog(main_sf, run_id, *, status=None, heartbeat_at=None) -> None:
    with session_scope(main_sf) as s:
        row = s.get(PaperTradingRunRecord, run_id)
        if status is not None:
            row.status = status
        if heartbeat_at is not None:
            row.heartbeat_at = heartbeat_at


def test_returns_unique_running_fresh(tmp_path) -> None:
    settings = paper_settings(tmp_path)
    _r, run_id, main_sf, _s = build_paper(tmp_path, settings=settings)  # running + fresh
    assert resolve_active_run_id(main_sf, settings.paper_validation_config()) == run_id


def test_none_when_no_running(tmp_path) -> None:
    settings = paper_settings(tmp_path)
    main_sf = main_factory(settings)  # empty catalog, no runs at all
    assert resolve_active_run_id(main_sf, settings.paper_validation_config()) is None


def test_none_when_stale_heartbeat(tmp_path) -> None:
    settings = paper_settings(tmp_path)
    _r, run_id, main_sf, _s = build_paper(tmp_path, settings=settings)
    _patch_catalog(main_sf, run_id, heartbeat_at=utc_now() - STALE)  # running but stale
    assert resolve_active_run_id(main_sf, settings.paper_validation_config()) is None


def test_none_when_stopped_even_if_recent(tmp_path) -> None:
    settings = paper_settings(tmp_path)
    _r, run_id, main_sf, _s = build_paper(tmp_path, settings=settings)
    _patch_catalog(main_sf, run_id, status="stopped", heartbeat_at=utc_now())  # status gate wins
    assert resolve_active_run_id(main_sf, settings.paper_validation_config()) is None


def test_none_when_ambiguous_multiple_running_fresh(tmp_path) -> None:
    settings = paper_settings(tmp_path)
    main_sf = main_factory(settings)
    build_paper(tmp_path, settings=settings, main_sf=main_sf)  # run #1: running + fresh
    build_paper(tmp_path, settings=settings, main_sf=main_sf)  # run #2: running + fresh
    # two live owners (e.g. split-brain) → ambiguous → None (caller must fail closed)
    assert resolve_active_run_id(main_sf, settings.paper_validation_config()) is None


def test_ignores_stale_second_run(tmp_path) -> None:
    settings = paper_settings(tmp_path)
    main_sf = main_factory(settings)
    _r1, id1, _sf1, _ = build_paper(tmp_path, settings=settings, main_sf=main_sf)
    _r2, id2, _sf2, _ = build_paper(tmp_path, settings=settings, main_sf=main_sf)
    _patch_catalog(main_sf, id2, heartbeat_at=utc_now() - STALE)  # #2 crashed / stale
    assert resolve_active_run_id(main_sf, settings.paper_validation_config()) == id1
