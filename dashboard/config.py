"""Dashboard configuration (Phase 7 — source of truth).

Read-only monitoring + stop-direction-only controls (Master Plan §17 / plan §23).
Loopback by default; a non-empty ``auth_token`` is required to invoke the two
stop-only mutating endpoints. The dashboard NEVER trades.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DashboardConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8787
    auth_token: str = ""

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("host must be non-empty")
        if not (0 < self.port < 65536):
            raise ValueError("port must be in 1..65535")

    @property
    def controls_enabled(self) -> bool:
        """Mutating (pause/halt) endpoints are honored only with a non-empty token."""
        return bool(self.auth_token)
