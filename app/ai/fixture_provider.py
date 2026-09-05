"""Offline, deterministic analyst provider (Phase 5).

Returns a canned raw response string, or simulates an infrastructure failure by
construction. No network, no ``anthropic`` dependency, no credentials.
"""

from __future__ import annotations

from app.ai.provider import AnalystProvider, AnalystRequest
from app.exceptions import AIError


class FixtureAnalystProvider(AnalystProvider):
    def __init__(
        self, response: str = "", *, error: type[AIError] | None = None
    ) -> None:
        self._response = response
        self._error = error
        self.last_request: AnalystRequest | None = None

    def analyze(self, request: AnalystRequest) -> str:
        self.last_request = request  # for tests: assert no secrets in the prompt
        if self._error is not None:
            raise self._error("fixture analyst failure")
        return self._response
