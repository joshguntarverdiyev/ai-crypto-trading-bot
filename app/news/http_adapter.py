"""Real HTTP news adapter — CryptoPanic (Phase 8 — off by default).

Implements the frozen P5 ``NewsSourceAdapter`` for the documented free
**CryptoPanic** JSON API (Master Plan §B-5). ``httpx`` is imported **lazily**;
importing this module pulls no networking library, and the offline test suite
(which tests only the pure converter) never touches the network. An API token, if
used, is injected at **construction** and never logged.

Contract-bound (plan §7.2): the produced ``NewsItemRaw`` preserves the five
timestamps, asset tagging, and the frozen availability semantics — the P5
``NewsService`` gate is unchanged. Forward-only: ``available_at`` is the feed's
publish time (public availability), so the ``available_at <= decision_time`` rule
holds honestly (§7.1); no historical availability is fabricated (§8).

Infra/HTTP/parse failures raise ``NewsSourceError`` — never a permissive empty
result.
"""

from __future__ import annotations

from datetime import datetime

from app.exceptions import NewsSourceError
from app.news.adapter import NewsSourceAdapter
from app.news.models import NewsItemRaw
from app.time_utils import ensure_utc

_CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/"


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        # CryptoPanic uses e.g. "2026-09-06T12:00:00Z".
        return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def raw_items_from_cryptopanic(
    payload: object, *, source: str = "cryptopanic"
) -> list[NewsItemRaw]:
    """Pure converter: a CryptoPanic JSON payload → untrusted ``NewsItemRaw`` list.

    A malformed top-level shape raises ``NewsSourceError``; per-item bad fields are
    passed through (normalization/the gate classify them). ``available_at`` is set
    to the feed publish time (public availability) for honest forward gating.
    """
    if not isinstance(payload, dict):
        raise NewsSourceError(
            f"malformed CryptoPanic payload: expected object, got {type(payload)!r}"
        )
    results = payload.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        raise NewsSourceError("malformed CryptoPanic payload: 'results' is not a list")

    items: list[NewsItemRaw] = []
    for post in results:
        if not isinstance(post, dict):
            continue  # skip a malformed row; never fabricate content
        published = _parse_iso(post.get("published_at"))
        currencies = post.get("currencies") or []
        assets: tuple[str, ...] = ()
        if isinstance(currencies, list):
            assets = tuple(
                str(c.get("code")).upper()
                for c in currencies
                if isinstance(c, dict) and c.get("code")
            )
        source_id = post.get("id")
        items.append(
            NewsItemRaw(
                source=source,
                source_id=str(source_id) if source_id is not None else None,
                url=post.get("url") if isinstance(post.get("url"), str) else None,
                title=post.get("title") if isinstance(post.get("title"), str) else None,
                summary=post.get("title") if isinstance(post.get("title"), str) else None,
                published_at=published,
                discovered_at=published,
                # Forward-only public availability = feed publish time (§7.1).
                available_at=published,
                assets=assets,
            )
        )
    return items


class HttpNewsAdapter(NewsSourceAdapter):
    """CryptoPanic HTTP news source (off by default; token at construction)."""

    def __init__(
        self,
        *,
        auth_token: str = "",
        url: str = _CRYPTOPANIC_URL,
        source: str = "cryptopanic",
        timeout_seconds: float = 10.0,
        kind: str = "news",
    ) -> None:
        self._token = auth_token
        self._url = url
        self._source = source
        self._timeout = timeout_seconds
        self._kind = kind

    def fetch(self, *, now: datetime, since: datetime | None = None) -> list[NewsItemRaw]:
        import httpx  # noqa: PLC0415 (intentional lazy import)

        params: dict[str, str] = {"kind": self._kind, "public": "true"}
        if self._token:
            params["auth_token"] = self._token  # never logged
        try:
            resp = httpx.get(self._url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # HTTP/JSON/network failure → conservative HOLD upstream
            raise NewsSourceError(f"CryptoPanic fetch failed: {exc}") from exc
        return raw_items_from_cryptopanic(payload, source=self._source)
