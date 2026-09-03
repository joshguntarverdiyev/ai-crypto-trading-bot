"""Logging: secret redaction and idempotent configuration."""

from __future__ import annotations

import logging

from app.config import load_settings
from app.logging_config import JsonFormatter, configure_logging


def _format(record_msg: str, secrets: list[str]) -> str:
    formatter = JsonFormatter(secrets=secrets)
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=record_msg, args=(), exc_info=None,
    )
    return formatter.format(record)


def test_known_secret_literal_is_redacted() -> None:
    out = _format("connecting with value SUPERSECRETVALUE now", secrets=["SUPERSECRETVALUE"])
    assert "SUPERSECRETVALUE" not in out
    assert "REDACTED" in out


def test_sensitive_key_value_pairs_are_redacted() -> None:
    out = _format("api_key=abc123 token=def456 password=hunter2", secrets=[])
    assert "abc123" not in out
    assert "def456" not in out
    assert "hunter2" not in out
    assert out.count("REDACTED") >= 3


def test_settings_secrets_are_redacted_end_to_end() -> None:
    s = load_settings(_env_file=None, anthropic_api_key="LIVEKEY_XYZ")
    out = _format("using anthropic_api_key=LIVEKEY_XYZ", secrets=s.secret_values())
    assert "LIVEKEY_XYZ" not in out


def test_configure_logging_is_idempotent() -> None:
    s = load_settings(_env_file=None)
    configure_logging(s)
    configure_logging(s)
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, "_aict_handler", False)]
    assert len(ours) == 1
