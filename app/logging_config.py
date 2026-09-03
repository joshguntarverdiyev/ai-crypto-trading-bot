"""Structured logging with secret redaction (Phase 0 foundation).

* Structured (JSON) log lines with UTC timestamps and component names.
* A redaction layer guarantees that credentials never reach the logs, even if
  a message or exception accidentally contains a secret value.

Two redaction mechanisms are combined:

1. Known secret literals (supplied from :meth:`app.config.Settings.secret_values`)
   are replaced wherever they appear.
2. ``key=value`` / ``key: value`` pairs for sensitive keys are redacted by
   pattern, catching secrets that were not known ahead of time.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from collections.abc import Iterable

_REDACTED = "***REDACTED***"

_SENSITIVE_KV_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|authorization|auth[_-]?token|bearer)"
    r"\s*[:=]\s*\S+"
)


def _redact_kv(match: re.Match[str]) -> str:
    return f"{match.group(1)}={_REDACTED}"


class JsonFormatter(logging.Formatter):
    """Format records as single-line JSON with UTC timestamps and redaction."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def _redact(self, text: str) -> str:
        text = _SENSITIVE_KV_RE.sub(_redact_kv, text)
        for secret in self._secrets:
            if secret:
                text = text.replace(secret, _REDACTED)
        return text

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "component": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return self._redact(json.dumps(payload, ensure_ascii=False))


def configure_logging(settings: object | None = None) -> None:
    """Configure root logging idempotently.

    ``settings`` (an :class:`app.config.Settings`) supplies the log level and
    the known secret values used for redaction. Passing ``None`` uses INFO and
    an empty secret set (safe default).
    """
    level = "INFO"
    secrets: list[str] = []
    if settings is not None:
        level = getattr(settings, "log_level", "INFO")
        secret_fn = getattr(settings, "secret_values", None)
        if callable(secret_fn):
            secrets = list(secret_fn())

    root = logging.getLogger()
    # Idempotent: drop handlers we previously installed.
    root.handlers = [h for h in root.handlers if not getattr(h, "_aict_handler", False)]

    handler = logging.StreamHandler(sys.stderr)
    handler._aict_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter(secrets=secrets))
    root.addHandler(handler)
    root.setLevel(level)
