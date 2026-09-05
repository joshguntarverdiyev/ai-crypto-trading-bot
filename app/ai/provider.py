"""Analyst provider interface (Phase 5).

Mirrors the Phase 1 adapter boundary. The provider is the ONLY place a real
Anthropic SDK call is added later; it is deferred here (no ``anthropic``
dependency, no network in Phase 5). Credentials, if ever needed, are injected at
provider *construction* by a later phase — they are never passed through
``analyze`` and never placed in the prompt (Master Plan §17). The provider
returns the raw model text (JSON) so the caller can validate it strictly;
infrastructure failures raise ``AIUnavailableError`` / ``AITimeoutError``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AnalystRequest:
    """A fully-built, secret-free request. ``model_id`` is runtime-resolved."""

    prompt: str
    model_id: str
    model_class: str
    prompt_version: str
    timeout_seconds: float


class AnalystProvider(ABC):
    @abstractmethod
    def analyze(self, request: AnalystRequest) -> str:
        """Return the raw model response text (expected JSON).

        Infrastructure failure raises :class:`app.exceptions.AIUnavailableError`
        or :class:`app.exceptions.AITimeoutError` — never a permissive result.
        """
        raise NotImplementedError
