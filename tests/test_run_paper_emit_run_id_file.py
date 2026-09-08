"""scripts/run_paper.py --emit-run-id-file (offline; start_paper_system stubbed).

Publishes PAPER_RUN_ID=<run_id> atomically so systemd units resume the SAME run
without a hardcoded UUID.
"""

from __future__ import annotations

import glob
import types

from app.config import load_settings
from scripts import run_paper


class _SpyRunner:
    def __init__(self):
        self._cfg = types.SimpleNamespace(symbols=())

    def run(self, *a, **k):
        return 0

    def run_once(self, *a, **k):
        return []


def _wire(monkeypatch, tmp_path, *, run_id_out):
    def fake_load_settings(*_a, **_k):
        return load_settings(_env_file=None, database_url=f"sqlite:///{tmp_path}/main.db",
                             paper_validation_enabled=True)

    def fake_start(settings, main_sf, *, now, run_id=None):
        return _SpyRunner(), run_id or run_id_out, "hash123", now

    monkeypatch.setattr(run_paper, "load_settings", fake_load_settings)
    monkeypatch.setattr(run_paper, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(run_paper, "start_paper_system", fake_start)
    monkeypatch.setattr(run_paper, "close_paper_run", lambda *a, **k: None)


def _run_main(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["run_paper", *argv])
    return run_paper.main()


def test_emit_writes_run_id_new_run(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path, run_id_out="new-run-1")
    out = tmp_path / "sub" / "paper-run.env"  # nested dir is created
    rc = _run_main(monkeypatch, ["--startup-only", "--emit-run-id-file", str(out)])
    assert rc == 0
    assert out.read_text() == "PAPER_RUN_ID=new-run-1\n"
    assert glob.glob(str(out.parent / ".paper-run-*.tmp")) == []  # atomic: no temp left behind


def test_emit_writes_run_id_on_resume(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path, run_id_out="unused")
    out = tmp_path / "paper-run.env"
    rc = _run_main(monkeypatch,
                   ["--startup-only", "--run-id", "abc-123", "--emit-run-id-file", str(out)])
    assert rc == 0
    assert out.read_text() == "PAPER_RUN_ID=abc-123\n"


def test_no_emit_flag_writes_no_file(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path, run_id_out="new-run-1")
    out = tmp_path / "paper-run.env"
    assert _run_main(monkeypatch, ["--startup-only"]) == 0
    assert not out.exists()
