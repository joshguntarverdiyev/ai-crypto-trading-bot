"""Pure, redacted alert formatter (Phase 7).

Deterministic text builder for outbound alerts. It NEVER includes secrets: any
field value containing a configured secret is redacted. Pure function — offline
testable, no network.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.notifications.models import Alert

_REDACTED = "***REDACTED***"


def format_alert(alert: Alert, *, secrets: Iterable[str] = ()) -> str:
    """Render an alert to a single redacted text block."""
    secret_list = [s for s in secrets if s]

    def redact(value: str) -> str:
        out = value
        for s in secret_list:
            if s and s in out:
                out = out.replace(s, _REDACTED)
        return out

    lines = [f"[{alert.kind.value.upper()}] {redact(alert.title)}"]
    for key, value in alert.fields.items():
        lines.append(f"  {redact(str(key))}: {redact(str(value))}")
    lines.append(f"  at: {alert.at.isoformat()}")
    return "\n".join(lines)
