"""P9: production Telegram notifier is wired into the paper runner (offline, safe).

Proves the previously-missing wiring: run_paper builds a Notifier from settings and
passes it into start_paper_system, alerts reach the notifier, disabled stays safe, and
a notifier/transport failure can never affect paper execution/risk. No real Telegram
HTTP call is ever made (the conftest blocks sockets; these tests use fixture / fake
transports and fail if httpx.post is touched).
"""

from __future__ import annotations

import types

import pytest
from sqlalchemy import func, select

from app.database import session_scope
from app.models import PaperOrderRecord
from app.notifications import FixtureNotificationTransport, NotificationsConfig, Notifier
from app.notifications.config import NotificationTransportKind
from app.notifications.factory import build_notifier
from app.notifications.http_transport import TelegramHttpTransport
from app.paper import metrics
from app.paper.store import make_run_session_factory
from scripts import run_paper
from tests._p6_helpers import decision_now, exit_decision_time
from tests._p9_helpers import APPROVE, build_paper


# --- A. factory selects the right transport / None ----------------------------------
def test_build_notifier_selects_transport() -> None:
    http = build_notifier(
        NotificationsConfig(
            enabled=True, transport=NotificationTransportKind.HTTP,
            bot_token="tok", chat_id="chat",
        )
    )
    assert isinstance(http, Notifier)
    assert isinstance(http._transport, TelegramHttpTransport)  # not called (no network)

    fixture = build_notifier(NotificationsConfig(enabled=True))  # fixture is the default
    assert isinstance(fixture, Notifier)
    assert isinstance(fixture._transport, FixtureNotificationTransport)

    assert build_notifier(NotificationsConfig(enabled=False)) is None  # disabled → None


# --- run_paper wiring harness -------------------------------------------------------
class _SpyRunner:
    def __init__(self):
        self._cfg = types.SimpleNamespace(symbols=())

    def run(self, *a, **k):
        return 0

    def run_once(self, *a, **k):
        return []


def _run_startup_only(monkeypatch, tmp_path, **settings_overrides):
    captured: dict[str, object] = {}

    def fake_load_settings(*_a, **_k):
        from app.config import load_settings

        return load_settings(
            _env_file=None, database_url=f"sqlite:///{tmp_path}/main.db",
            paper_validation_enabled=True, **settings_overrides,
        )

    def fake_start(settings, main_sf, *, now, run_id=None, notifier=None):
        captured["notifier"] = notifier
        return _SpyRunner(), run_id or "run-1", "hash", now

    monkeypatch.setattr(run_paper, "load_settings", fake_load_settings)
    monkeypatch.setattr(run_paper, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(run_paper, "start_paper_system", fake_start)
    monkeypatch.setattr(run_paper, "close_paper_run", lambda *_a, **_k: None)
    monkeypatch.setattr("sys.argv", ["run_paper", "--startup-only"])
    rc = run_paper.main()
    return rc, captured


# --- B. production wiring creates AND passes a notifier ------------------------------
def test_run_paper_wires_notifier_when_enabled(monkeypatch, tmp_path) -> None:
    rc, captured = _run_startup_only(
        monkeypatch, tmp_path, telegram_enabled=True, telegram_transport="fixture"
    )
    assert rc == 0
    assert isinstance(captured["notifier"], Notifier)  # was None before this fix


# --- D. disabled notifications pass None (safe, unchanged) ---------------------------
def test_run_paper_passes_none_when_disabled(monkeypatch, tmp_path) -> None:
    rc, captured = _run_startup_only(monkeypatch, tmp_path, telegram_enabled=False)
    assert rc == 0
    assert captured["notifier"] is None


# --- C. an alert reaches the notifier in the integration path -----------------------
def test_alert_reaches_notifier_integration(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("httpx.post", lambda *a, **k: pytest.fail("no real Telegram call"))
    transport = FixtureNotificationTransport()
    notifier = Notifier(transport, NotificationsConfig(enabled=True))
    build_paper(tmp_path, notifier=notifier)  # startup emits restart_alert via the runner
    assert transport.sent  # PaperRunner received the notifier and an alert flowed


# --- E. a raising transport cannot affect execution / risk (req 8) ------------------
class _RaisingTransport:
    def send(self, text: str) -> bool:
        raise RuntimeError("telegram down")


def _durable_state(cfg, run_id) -> tuple:
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    view = metrics.build_view(run_sf, starting_equity=cfg.starting_equity, primary_tf_seconds=3600)
    trades = metrics.reconstruct_trades(run_sf)
    with session_scope(run_sf) as s:
        orders = s.scalar(select(func.count()).select_from(PaperOrderRecord)) or 0
    return (view.ending_equity, tuple(t.net_pnl for t in trades), int(orders))


def _run_entry_exit(tmp_path, notifier):
    runner, run_id, _main_sf, settings = build_paper(
        tmp_path, analyst_response=APPROVE, notifier=notifier
    )
    runner.run_once(decision_now())       # entry
    runner.run_once(exit_decision_time())  # exit
    return _durable_state(settings.paper_validation_config(), run_id)


def test_transport_failure_does_not_affect_execution(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("httpx.post", lambda *a, **k: pytest.fail("no real Telegram call"))
    # A notifier whose transport raises on EVERY send (startup + per-boundary alerts).
    raising = Notifier(_RaisingTransport(), NotificationsConfig(enabled=True))

    with_failure = _run_entry_exit(tmp_path / "boom", raising)   # must not raise
    baseline = _run_entry_exit(tmp_path / "none", None)          # notifier=None

    assert with_failure == baseline  # identical equity, trade P&L, and order count
