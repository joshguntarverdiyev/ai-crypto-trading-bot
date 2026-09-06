"""Dashboard auth (Phase 7) — token gate for the stop-only control endpoints.

Read views are available on the loopback bind; the two mutating endpoints
(pause/halt) require a non-empty, correct token supplied via the
``X-Auth-Token`` header (or ``Authorization: Bearer <token>``). If no token is
configured, controls are refused entirely (Master Plan §17 / plan §23/§25).
Comparison is constant-time.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from dashboard.config import DashboardConfig


def make_control_guard(config: DashboardConfig):  # noqa: ANN201 (FastAPI dependency factory)
    """Return a FastAPI dependency that authorizes a stop-only control request."""

    async def guard(
        x_auth_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> None:
        if not config.controls_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="controls disabled (no auth token configured)",
            )
        supplied = x_auth_token
        if supplied is None and authorization and authorization.lower().startswith("bearer "):
            supplied = authorization[7:]
        if not supplied or not hmac.compare_digest(supplied, config.auth_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token"
            )

    return guard
