"""Repository hygiene: .gitignore protects secrets/artifacts; .env.example is empty."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_gitignore_protects_sensitive_paths() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for needle in (".env", "*.db", ".venv", "__pycache__", "logs/"):
        assert needle in text, f"{needle!r} missing from .gitignore"


def test_env_example_has_no_populated_secrets() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    sensitive = (
        "EXCHANGE_API_KEY",
        "EXCHANGE_API_SECRET",
        "ANTHROPIC_API_KEY",
        "TELEGRAM_BOT_TOKEN",
    )
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in sensitive:
            assert value.strip() == "", f"{key} must be empty in .env.example"


def test_no_committed_env_file() -> None:
    """The security property is that ``.env`` is never COMMITTED/tracked — not that a
    local (git-ignored) ``.env`` is absent. A developer/operator legitimately keeps a
    local ``.env`` for runtime secrets; what must never happen is it entering git."""
    # 1. .env must be git-ignored (defense against accidental `git add`).
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".env"], cwd=ROOT, check=False
    )
    assert ignored.returncode == 0, ".env must be git-ignored"

    # 2. .env must not be tracked by git (the real "not committed" property).
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"],
        cwd=ROOT, check=False, capture_output=True,
    )
    assert tracked.returncode != 0, ".env must not be tracked/committed in git"
