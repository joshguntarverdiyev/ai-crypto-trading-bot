"""scripts/run_paper.py --startup-only flag (offline; start_paper_system stubbed)."""

from __future__ import annotations

import types

from app.config import load_settings
from scripts import run_paper


class _SpyRunner:
    """Records run()/run_once() calls; fails if they are called under --startup-only."""

    def __init__(self):
        self.run_calls = 0
        self.run_once_calls = 0
        self._cfg = types.SimpleNamespace(symbols=())

    def run(self, *a, **k):
        self.run_calls += 1
        return 0

    def run_once(self, *a, **k):
        self.run_once_calls += 1
        return []


def _wire(monkeypatch, tmp_path, *, runner, universe_hash="hash123"):
    """Stub main()'s IO: offline settings (temp catalog DB) + stubbed orchestrator."""
    calls = {"start": 0, "close": [], "start_kwargs": None}

    def fake_load_settings(*_a, **_k):
        return load_settings(_env_file=None, database_url=f"sqlite:///{tmp_path}/main.db",
                             paper_validation_enabled=True)

    def fake_start(settings, main_sf, *, now, run_id=None):
        calls["start"] += 1
        calls["start_kwargs"] = {"run_id": run_id, "now": now}
        return runner, run_id or "new-run-1", universe_hash, now

    def fake_close(main_sf, run_id, *, status="stopped"):
        calls["close"].append((run_id, status))

    monkeypatch.setattr(run_paper, "load_settings", fake_load_settings)
    monkeypatch.setattr(run_paper, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(run_paper, "start_paper_system", fake_start)
    monkeypatch.setattr(run_paper, "close_paper_run", fake_close)
    return calls


def _run_main(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["run_paper", *argv])
    return run_paper.main()


# --- startup-only: NEW run → one startup, no processing ---------------------------
def test_startup_only_new_run_no_processing(monkeypatch, tmp_path) -> None:
    runner = _SpyRunner()
    calls = _wire(monkeypatch, tmp_path, runner=runner)
    rc = _run_main(monkeypatch, ["--startup-only"])
    assert rc == 0
    assert calls["start"] == 1                       # startup orchestration invoked once
    assert calls["start_kwargs"]["run_id"] is None   # NEW run
    assert runner.run_calls == 0 and runner.run_once_calls == 0  # NO processing
    assert calls["close"] == [("new-run-1", "stopped")]          # run closed/resumable


# --- startup-only: RESUME → one startup (load), no processing, no re-select --------
def test_startup_only_resume_no_processing(monkeypatch, tmp_path) -> None:
    runner = _SpyRunner()
    calls = _wire(monkeypatch, tmp_path, runner=runner)
    rc = _run_main(monkeypatch, ["--startup-only", "--run-id", "abc-123"])
    assert rc == 0
    assert calls["start"] == 1
    assert calls["start_kwargs"]["run_id"] == "abc-123"   # resume path (start_paper_system loads)
    assert runner.run_calls == 0 and runner.run_once_calls == 0
    assert calls["close"] == [("abc-123", "stopped")]


# --- startup-only NEVER calls run()/run_once() (guard) ----------------------------
def test_startup_only_never_processes_boundary(monkeypatch, tmp_path) -> None:
    class Boom(_SpyRunner):
        def run(self, *a, **k):
            raise AssertionError("run() must NOT be called under --startup-only")

        def run_once(self, *a, **k):
            raise AssertionError("run_once() must NOT be called under --startup-only")

    calls = _wire(monkeypatch, tmp_path, runner=Boom())
    assert _run_main(monkeypatch, ["--startup-only"]) == 0
    assert calls["start"] == 1


# --- --startup-only + --supervise is rejected, runner never built -----------------
def test_startup_only_conflicts_with_supervise(monkeypatch, tmp_path) -> None:
    calls = _wire(monkeypatch, tmp_path, runner=_SpyRunner())
    rc = _run_main(monkeypatch, ["--startup-only", "--supervise"])
    assert rc == 2                       # clear failure code
    assert calls["start"] == 0           # startup NOT invoked; runner not built
    assert calls["close"] == []


# --- normal finite run STILL processes (backward compat) --------------------------
def test_normal_run_still_processes_once(monkeypatch, tmp_path) -> None:
    runner = _SpyRunner()
    calls = _wire(monkeypatch, tmp_path, runner=runner)
    rc = _run_main(monkeypatch, [])  # default finite run (iterations=1)
    assert rc == 0
    assert runner.run_once_calls == 1 and runner.run_calls == 0   # one boundary sweep
    assert calls["close"] == [("new-run-1", "stopped")]


# --- normal supervise path calls run() (backward compat) --------------------------
def test_normal_supervise_calls_run(monkeypatch, tmp_path) -> None:
    runner = _SpyRunner()
    _wire(monkeypatch, tmp_path, runner=runner)
    # stub the signal handler install (no real SIGTERM handler in the test process)
    monkeypatch.setattr(run_paper, "_install_graceful_stop", lambda: None)
    rc = _run_main(monkeypatch, ["--supervise"])
    assert rc == 0
    assert runner.run_calls == 1 and runner.run_once_calls == 0


# --- the "P9 frozen universe" log uses the AUTHORITATIVE T0 from start_paper_system --
def test_frozen_universe_log_uses_returned_t0(monkeypatch, tmp_path, caplog) -> None:
    import logging
    from datetime import UTC, datetime

    runner = _SpyRunner()
    calls = {"n": 0}
    frozen_t0 = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)  # authoritative persisted T0

    def fake_load_settings(*_a, **_k):
        return load_settings(_env_file=None, database_url=f"sqlite:///{tmp_path}/main.db",
                             paper_validation_enabled=True)

    def fake_start(settings, main_sf, *, now, run_id=None):
        # simulate a RESUME: return a frozen T0 that DIFFERS from `now` (the process clock)
        calls["n"] += 1
        assert now != frozen_t0
        return runner, "resume-run", "deadbeefhash", frozen_t0

    monkeypatch.setattr(run_paper, "load_settings", fake_load_settings)
    monkeypatch.setattr(run_paper, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(run_paper, "start_paper_system", fake_start)
    monkeypatch.setattr(run_paper, "close_paper_run", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", ["run_paper", "--startup-only", "--run-id", "resume-run"])
    with caplog.at_level(logging.INFO, logger="scripts.run_paper"):
        assert run_paper.main() == 0
    frozen_line = next(m for m in caplog.messages if "P9 frozen universe" in m)
    assert f"t0={frozen_t0.isoformat()}" in frozen_line  # authoritative frozen T0, NOT process time
