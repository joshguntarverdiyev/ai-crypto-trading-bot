"""Telegram can NEVER place a trade (Master Plan §17, plan §24)."""

from __future__ import annotations

from pathlib import Path

from app.notifications.notifier import Notifier

_NOTIF_DIR = Path(__file__).resolve().parent.parent / "app" / "notifications"

# Trading/execution runtime the notifications layer must never import.
_FORBIDDEN = (
    "app.execution",
    "app.engine",
    "app.sizing",
    "app.strategy",
    "app.risk.manager",
    "app.portfolio.ledger",
    "backtesting",
)


def _import_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("from "):
            targets.append(line.split()[1])
        elif line.startswith("import "):
            targets.extend(p.strip().split()[0] for p in line[len("import "):].split(","))
    return targets


def test_notifications_do_not_import_trading_runtime() -> None:
    for path in _NOTIF_DIR.glob("*.py"):
        targets = _import_targets(path.read_text(encoding="utf-8"))
        for forbidden in _FORBIDDEN:
            offenders = [t for t in targets if t == forbidden or t.startswith(forbidden + ".")]
            assert not offenders, f"{path.name} imports trading runtime {offenders!r}"


def test_notifier_exposes_no_order_placement_api() -> None:
    public = {name for name in dir(Notifier) if not name.startswith("_")}
    # Only alerting + stop-only control application are exposed.
    assert public == {"send_alert", "parse_inbound", "apply_command"}
    for banned in ("order", "buy", "sell", "trade", "execute", "place"):
        assert not any(banned in name.lower() for name in public)
