"""Real Google Gemini analyst provider (advisory only; off by default).

Implements the frozen P5 ``AnalystProvider`` using the ``google-genai`` SDK.
``google.genai`` is imported **lazily**; importing this module pulls no SDK and the
offline test suite never touches the network. The API key is injected at
**construction** (Master Plan §17) — it is NEVER passed through ``analyze`` and
NEVER placed in the prompt (the prompt is the secret-free, versioned builder
output). The model id is runtime-resolved from versioned config and carried on
``request`` (§0.1-2).

Gemini is asked for JSON output (``response_mime_type="application/json"``), but the
authoritative gate is the UNCHANGED strict ``validate_analyst_response`` upstream —
this provider only returns the raw model text. Gemini remains strictly advisory:
any infrastructure failure raises ``AIUnavailableError`` / ``AITimeoutError``
(→ HOLD), never a permissive result. It holds no exchange credentials, places no
orders, and can never relax a RiskManager limit — the RiskManager (P6) is final.
"""

from __future__ import annotations

from app.ai.provider import AnalystProvider, AnalystRequest
from app.exceptions import AITimeoutError, AIUnavailableError


class GeminiAnalystProvider(AnalystProvider):
    def __init__(self, *, api_key: str, max_tokens: int = 1024) -> None:
        if not api_key:
            raise ValueError("GeminiAnalystProvider requires a non-empty api_key")
        self._api_key = api_key  # injected at construction; never in the prompt/logs
        self._max_tokens = max_tokens

    def analyze(self, request: AnalystRequest) -> str:
        try:
            from google import genai  # noqa: PLC0415 (intentional lazy import)
            from google.genai import types  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - only when extra missing
            raise AIUnavailableError(
                "google-genai is not installed; install the '[gemini]' extra for ai_provider=gemini"
            ) from exc

        try:
            # timeout is milliseconds in google-genai's HttpOptions.
            client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=int(request.timeout_seconds * 1000)),
            )
            response = client.models.generate_content(
                model=request.model_id,
                contents=request.prompt,
                config=types.GenerateContentConfig(
                    # JSON mode; the strict upstream validator stays authoritative.
                    response_mime_type="application/json",
                    max_output_tokens=self._max_tokens,
                ),
            )
        except Exception as exc:  # noqa: BLE001 (map ALL infra failures to safe HOLD)
            if _is_timeout(exc):
                raise AITimeoutError(f"gemini request timed out: {exc}") from exc
            raise AIUnavailableError(f"gemini request failed: {exc}") from exc

        return _extract_text(response)


def _is_timeout(exc: Exception) -> bool:
    """Best-effort timeout detection (google-genai has no single public timeout type).

    The distinction only affects the audit ``AnalystFailure`` label (TIMEOUT vs
    UNAVAILABLE) — both map to a conservative HOLD, so misclassification is safe."""
    name = exc.__class__.__name__.lower()
    return "timeout" in name or "deadline" in name


def _extract_text(response: object) -> str:
    """Return the response text (empty string if absent → SCHEMA_INVALID → HOLD)."""
    text = getattr(response, "text", None)
    return text if isinstance(text, str) else ""
