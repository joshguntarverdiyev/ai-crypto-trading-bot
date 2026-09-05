"""KillSwitch state machine + persistence (survives restart, HALT dominates)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.database import init_db, make_engine, make_session_factory
from app.risk.kill_switch import KillSwitch, KillSwitchStatus

AT = datetime(2026, 1, 2, tzinfo=UTC)


def _sf(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/ks.db")
    init_db(engine)
    return make_session_factory(engine)


def test_default_running(tmp_path) -> None:
    ks = KillSwitch(_sf(tmp_path))
    assert ks.current().status is KillSwitchStatus.RUNNING


def test_pause_then_auto_resume(tmp_path) -> None:
    ks = KillSwitch(_sf(tmp_path))
    ks.pause("abnormal_spread", AT)
    assert ks.current().status is KillSwitchStatus.PAUSED
    assert ks.resume(AT) is True
    assert ks.current().status is KillSwitchStatus.RUNNING


def test_halt_requires_manual_reset(tmp_path) -> None:
    ks = KillSwitch(_sf(tmp_path))
    ks.halt("drawdown_limit", AT)
    assert ks.current().status is KillSwitchStatus.HALTED
    assert ks.resume(AT) is False  # auto-resume cannot clear a HALT
    assert ks.current().status is KillSwitchStatus.HALTED
    ks.manual_reset(AT)
    assert ks.current().status is KillSwitchStatus.RUNNING


def test_halt_dominates_pause(tmp_path) -> None:
    ks = KillSwitch(_sf(tmp_path))
    ks.halt("drawdown_limit", AT)
    ks.pause("abnormal_spread", AT)  # must not downgrade a HALT
    assert ks.current().status is KillSwitchStatus.HALTED


def test_halt_survives_restart(tmp_path) -> None:
    sf = _sf(tmp_path)
    KillSwitch(sf).halt("persistence_failure", AT)
    # a fresh KillSwitch over the same DB (process restart) still sees HALTED
    assert KillSwitch(sf).current().status is KillSwitchStatus.HALTED
