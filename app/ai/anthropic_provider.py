"""Real Anthropic analyst provider (Phase 8 — off by default; advisory only).

Implements the frozen P5 ``AnalystProvider`` using the Anthropic SDK. ``anthropic``
is imported **lazily**; importing this module pulls no SDK and the offline test
suite never touches the network. The API key is injected at **construction**
(Master Plan §17) — it is NEVER passed through ``analyze`` and NEVER placed in the
prompt (the prompt is the secret-free, versioned builder output). The model id is
runtime-resolved from versioned config and carried on ``request`` (§0.1-2).

Claude remains strictly advisory: it returns raw JSON text for strict validation
upstream; any infrastructure failure raises ``AIUnavailableError`` /
``AITimeoutError`` (→ HOLD), never a permissive result. It holds no exchange
credentials, places no orders, and can never relax a RiskManager limit.
"""

from __future__ import annotations

from app.ai.provider import AnalystProvider, AnalystRequest
from app.exceptions import AITimeoutError, AIUnavailableError


class AnthropicAnalystProvider(AnalystProvider):
    def __init__(self, *, api_key: str, max_tokens: int = 1024) -> None:
        if not api_key:
            raise ValueError("AnthropicAnalystProvider requires a non-empty api_key")
        self._api_key = api_key  # injected at construction; never in the prompt/logs
        self._max_tokens = max_tokens

    def analyze(self, request: AnalystRequest) -> str:
        try:
            import anthropic  # noqa: PLC0415 (intentional lazy import)
        except ImportError as exc:  # pragma: no cover - only when extra missing
            raise AIUnavailableError(
                "anthropic is not installed; install the '[shadow]' extra for ai_provider=anthropic"
            ) from exc

        timeout_exc = getattr(anthropic, "APITimeoutError", None)
        try:
            client = anthropic.Anthropic(api_key=self._api_key, timeout=request.timeout_seconds)
            response = client.messages.create(
                model=request.model_id,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": request.prompt}],
            )
        except Exception as exc:  # noqa: BLE001 (map ALL infra failures to safe HOLD)
            if timeout_exc is not None and isinstance(exc, timeout_exc):
                raise AITimeoutError(f"anthropic request timed out: {exc}") from exc
            raise AIUnavailableError(f"anthropic request failed: {exc}") from exc

        return _extract_text(response)


def _extract_text(response: object) -> str:
    """Concatenate the text blocks of an Anthropic messages response."""
    content = getattr(response, "content", None)
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)
