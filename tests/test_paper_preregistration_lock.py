"""P9: pre-registration digest is LOCKED before the first boundary (§35.4).

A NEW run persists ``paper_trading_runs.prereg_digest`` at creation (before any boundary
is processed); a RESUME recomputes and verifies it, failing closed on a changed or missing
(NULL) digest. Offline/deterministic — no external API calls.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.database import session_scope
from app.exceptions import PaperRunError
from app.models import (
    PaperDecisionRecord,
    PaperFillRecord,
    PaperOrderRecord,
    PaperTradingRunRecord,
)
from app.paper.metrics import preregistration
from app.paper.store import close_paper_run, release_run_lock
from tests._p9_helpers import build_paper, paper_settings


def _persisted_digest(main_sf, run_id) -> str | None:
    with session_scope(main_sf) as s:
        return s.get(PaperTradingRunRecord, run_id).prereg_digest


def _counts(run_sf) -> tuple[int, int, int]:
    with session_scope(run_sf) as s:
        d = s.scalar(select(func.count()).select_from(PaperDecisionRecord)) or 0
        o = s.scalar(select(func.count()).select_from(PaperOrderRecord)) or 0
        f = s.scalar(select(func.count()).select_from(PaperFillRecord)) or 0
    return int(d), int(o), int(f)


# --- A. NEW run persists a non-null 64-char hex digest -------------------------------
def test_new_run_persists_prereg_digest(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: pytest.fail("no network on NEW run"))
    _runner, run_id, main_sf, _settings = build_paper(tmp_path)
    digest = _persisted_digest(main_sf, run_id)
    assert digest is not None
    assert len(digest) == 64
    int(digest, 16)  # hex


# --- B. persisted digest == preregistration(run_id, cfg).digest ----------------------
def test_persisted_digest_matches_preregistration(tmp_path) -> None:
    _runner, run_id, main_sf, settings = build_paper(tmp_path)
    expected = preregistration(run_id, settings.paper_validation_config()).digest
    assert _persisted_digest(main_sf, run_id) == expected


# --- E. startup (NEW) persists the digest with ZERO boundary processing --------------
def test_new_run_zero_processing_but_digest_locked(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: pytest.fail("no network at startup"))
    runner, run_id, main_sf, _settings = build_paper(tmp_path)  # no run_once() called
    assert _persisted_digest(main_sf, run_id) is not None       # digest locked at startup
    assert _counts(runner._sf) == (0, 0, 0)                     # no decisions/orders/fills


# --- C. RESUME with the same config succeeds; digest left unchanged ------------------
def test_resume_same_config_keeps_digest(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path)
    digest0 = _persisted_digest(main_sf, run_id)

    release_run_lock(runner._lock)                 # clean shutdown
    close_paper_run(main_sf, run_id, status="stopped")

    runner2, rid2, _msf, _s = build_paper(
        tmp_path, run_id=run_id, settings=settings, main_sf=main_sf
    )
    assert rid2 == run_id
    assert _persisted_digest(main_sf, run_id) == digest0  # verified, NOT overwritten


# --- D. RESUME with a changed pre-registered knob fails closed -----------------------
def test_resume_changed_config_fails_closed(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path)
    digest0 = _persisted_digest(main_sf, run_id)

    release_run_lock(runner._lock)
    close_paper_run(main_sf, run_id, status="stopped")

    # Same DB paths (tmp_path) but a DIFFERENT pre-registered value → different digest.
    changed = paper_settings(tmp_path, paper_validation_days=20)
    with pytest.raises(PaperRunError, match="pre-registration mismatch"):
        build_paper(tmp_path, run_id=run_id, settings=changed, main_sf=main_sf)

    assert _persisted_digest(main_sf, run_id) == digest0  # unchanged (no late overwrite)
    assert _counts(runner._sf) == (0, 0, 0)               # no boundary processed


# --- D2. RESUME with a NULL digest fails closed (integrity rule) ---------------------
def test_resume_null_digest_fails_closed(tmp_path) -> None:
    runner, run_id, main_sf, settings = build_paper(tmp_path)

    with session_scope(main_sf) as s:               # simulate an incomplete/legacy run
        s.get(PaperTradingRunRecord, run_id).prereg_digest = None
    release_run_lock(runner._lock)
    close_paper_run(main_sf, run_id, status="stopped")

    with pytest.raises(PaperRunError, match="no pre-registration digest"):
        build_paper(tmp_path, run_id=run_id, settings=settings, main_sf=main_sf)
    assert _counts(runner._sf) == (0, 0, 0)         # no boundary processed
