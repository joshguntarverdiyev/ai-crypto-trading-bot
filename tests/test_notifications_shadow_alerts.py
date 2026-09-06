"""Phase 8 shadow alerts — outbound only, redacted, never a trade (offline)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.market_data.models import Symbol
from app.notifications.config import NotificationsConfig
from app.notifications.models import AlertKind
from app.notifications.notifier import Notifier
from app.notifications.transport import FixtureNotificationTransport
from app.shadow import alerts
from app.shadow.models import ShadowOutcome, ShadowResult

_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _would_trade_result() -> ShadowResult:
    return ShadowResult(
        outcome=ShadowOutcome.WOULD_TRADE, stage="execution", reason="ok",
        symbol=Symbol.parse("BTC/USDT"), decision_time=_AT,
        hyp_side="buy", hyp_quantity=Decimal("0.1"), hyp_entry_ref=Decimal("100"),
        hyp_fill_price=Decimal("100.1"), hyp_fill_state="filled",
    )


def test_would_trade_alert_is_labelled_hypothetical() -> None:
    alert = alerts.would_trade_alert(_would_trade_result(), at=_AT)
    assert alert.kind is AlertKind.SHADOW_WOULD_TRADE
    assert "hypothetical" in alert.title.lower()
    assert "not executed" in alert.title.lower()
    assert "no order was placed" in alert.fields.get("note", "").lower()


def test_alert_send_redacts_secrets() -> None:
    transport = FixtureNotificationTransport()
    notifier = Notifier(transport, NotificationsConfig(enabled=True), secrets=("Süper-Secret",))
    result = _would_trade_result()
    # Inject a secret into a field to prove redaction on the shadow path.
    result.market_summary["leak"] = "Süper-Secret"
    alert = alerts.would_trade_alert(result, at=_AT)
    alert.fields["leak"] = "Süper-Secret"
    assert notifier.send_alert(alert) is True
    assert "Süper-Secret" not in transport.sent[0]
    assert "REDACTED" in transport.sent[0]


def test_inbound_still_stop_only_on_shadow_channel() -> None:
    notifier = Notifier(FixtureNotificationTransport(), NotificationsConfig(enabled=True))
    # Trade-like inbound is rejected; only pause/halt are honored.
    for text in ("buy BTC", "trade", "would_trade", "execute now"):
        assert notifier.parse_inbound(text, actor="telegram:1") is None
    assert notifier.parse_inbound("pause data gap", actor="telegram:1") is not None
    assert notifier.parse_inbound("halt", actor="telegram:1") is not None
