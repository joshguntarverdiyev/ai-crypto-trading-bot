"""Real Telegram HTTP transport (Phase 7 — deferred/off; never used in tests).

Sends a message via the Telegram Bot API over HTTPS. It is OFF by default,
requires a bot token + chat id (kept EMPTY in the repo), imports ``httpx``
lazily, and is NEVER exercised by the offline test suite (the network-blocking
conftest would reject a real socket anyway). It sends text only — it cannot place
a trade. Live wiring/operation is a later, operational concern.
"""

from __future__ import annotations


class TelegramHttpTransport:
    def __init__(self, *, bot_token: str, chat_id: str, timeout_seconds: float = 10.0) -> None:
        if not (bot_token and chat_id):
            raise ValueError("TelegramHttpTransport requires bot_token and chat_id")
        self._token = bot_token
        self._chat_id = chat_id
        self._timeout = timeout_seconds

    def send(self, text: str) -> bool:
        # httpx is imported lazily so the core import graph stays dependency-light,
        # and so merely importing this module never pulls a networking library.
        import httpx  # noqa: PLC0415 (intentional lazy import)

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            resp = httpx.post(
                url,
                json={"chat_id": self._chat_id, "text": text},
                timeout=self._timeout,
            )
        except Exception:
            return False
        return resp.status_code == 200
