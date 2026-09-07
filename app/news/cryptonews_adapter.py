"""Crypto News API adapter (Phase 9 — real HTTP; off by default; advisory input).

Implements the frozen P5 ``NewsSourceAdapter`` boundary for `cryptonews-api.com`.
``httpx`` is imported **lazily**; importing this module pulls no networking library
and the offline test suite exercises only the pure converter / timestamp parser.

Two adapters:

* ``CryptoNewsApiAdapter`` — the REAL HTTP source used by the Tier-2 poller
  (``scripts/run_news_ingest``). ``fetch_result`` returns articles + ingestion
  provenance (HTTP status, response hash, token-free request params). ``fetch``
  satisfies the ABC for a direct (Tier-1) read (``discovered_at = now``).
* ``IngestionStoreNewsAdapter`` — the DECISION-TIME read path: reads first_seen_at
  from the isolated ingestion store; performs NO boundary network I/O.

Security (§L): the API token comes only from config, is passed as a query param,
and is **never** logged or embedded in an error/provenance. Every transport
failure is re-raised as a token-free ``NewsSourceError`` (``from None`` so the
original token-bearing exception is not chained); the token is also registered in
``Settings.secret_values()`` for global log redaction.

Timestamps (§F): the provider ``date`` carries an explicit US-Eastern offset
(``-0400`` EDT / ``-0500`` EST). It is parsed to an **aware** datetime and
converted to UTC (never naive→UTC), so DST is correct by construction. A missing
offset or unparseable date ⇒ the item is rejected (never a fabricated timestamp).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from app.exceptions import NewsSourceError
from app.news.adapter import NewsSourceAdapter
from app.news.ingestion import IngestArticle, NewsIngestionStore
from app.news.models import NewsItemRaw
from app.time_utils import ensure_utc

_DEFAULT_BASE_URL = "https://cryptonews-api.com/api/v1"


@contextmanager
def _no_httpx_request_log() -> Iterator[None]:
    """Suppress httpx's INFO request-line for the duration of a call.

    The provider requires the token as a query param, so it is unavoidably part of
    the request URL. httpx's default ``httpx`` logger emits that full URL (token
    included) at INFO. This raises that logger's threshold to WARNING around the
    request so the token can never reach a log record — INDEPENDENTLY of whether the
    application's log-redaction (``configure_logging``) is installed. The previous
    level is restored afterwards; app-level secret redaction remains as defense in
    depth."""
    lg = logging.getLogger("httpx")
    prev = lg.level
    lg.setLevel(max(prev, logging.WARNING) if prev else logging.WARNING)
    try:
        yield
    finally:
        lg.setLevel(prev)


@dataclass(frozen=True)
class CryptoNewsConfig:
    """Crypto News API request parameters (token is a dedicated secret)."""

    token: str
    base_url: str = _DEFAULT_BASE_URL
    tickers: tuple[str, ...] = ("BTC", "ETH")
    items: int = 50
    max_pages: int = 1
    timeout_seconds: float = 10.0
    source: str = "cryptonewsapi"


@dataclass(frozen=True)
class FetchResult:
    """One poll's outcome: articles + ingestion provenance (token-free)."""

    articles: list[IngestArticle]
    http_status: int | None
    response_hash: str | None
    request_params: dict[str, object]
    rejects: list[tuple[str, str]] = field(default_factory=list)  # (reason, detail)


# --- timestamp parsing (explicit offset → UTC; DST-correct) ------------------
def parse_cryptonews_date(value: object) -> datetime | None:
    """Parse a Crypto News API ``date`` into aware UTC, honoring its explicit
    offset. Returns ``None`` (⇒ reject) when the value is missing, unparseable, or
    carries NO explicit offset (a naive time is never assumed to be UTC)."""
    if not isinstance(value, str) or not value.strip():
        return None
    dt: datetime | None = None
    try:
        dt = parsedate_to_datetime(value)  # RFC 2822, e.g. "Fri, 20 Jan 2023 10:30:00 -0500"
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(value)  # ISO-8601 fallback (must carry offset)
        except ValueError:
            return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None  # no explicit offset → not defensible; never naive→UTC
    return dt.astimezone(UTC)


# --- identity + fingerprints -------------------------------------------------
def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:40]


def _canonical_url(url: str) -> str:
    """Strip a trailing slash + query/fragment for a stable URL identity."""
    base = url.split("#", 1)[0].split("?", 1)[0].rstrip("/").strip().lower()
    return base


def article_identity(news_id: object, url: object, source_name: object, title: str,
                     date_str: object) -> tuple[str, str | None]:
    """Deterministic identity (news_id → canonical-url hash → fingerprint).

    Returns (id, provider_news_id). Never random."""
    provider_news_id = str(news_id) if news_id is not None and str(news_id) else None
    if provider_news_id:
        return _sha(f"id:{provider_news_id}"), provider_news_id
    if isinstance(url, str) and url.strip():
        return _sha(f"url:{_canonical_url(url)}"), None
    basis = f"fp:{source_name}|{title.strip().lower()}|{date_str}"
    return _sha(basis), None


# --- pure converter ----------------------------------------------------------
def parse_cryptonews_payload(
    payload: object, *, source: str = "cryptonewsapi"
) -> tuple[list[IngestArticle], list[tuple[str, str]]]:
    """CryptoNews JSON payload → (articles, rejects). A malformed TOP-LEVEL shape
    raises ``NewsSourceError`` (never a valid-empty result). Per-item problems
    (bad/missing date, missing title) reject that item with an auditable reason —
    never a fabricated timestamp, never random content."""
    if not isinstance(payload, dict):
        raise NewsSourceError(
            f"malformed Crypto News API payload: expected object, got {type(payload)!r}"
        )
    data = payload.get("data")
    if data is None:
        return [], []
    if not isinstance(data, list):
        raise NewsSourceError("malformed Crypto News API payload: 'data' is not a list")

    articles: list[IngestArticle] = []
    rejects: list[tuple[str, str]] = []
    for post in data:
        if not isinstance(post, dict):
            rejects.append(("malformed_row", "row is not an object"))
            continue
        title = post.get("title")
        if not isinstance(title, str) or not title.strip():
            rejects.append(("missing_title", str(post.get("news_url"))))
            continue
        published = parse_cryptonews_date(post.get("date"))
        if published is None:
            rejects.append(("invalid_date", f"{title[:40]!r}: {post.get('date')!r}"))
            continue
        url_val, name_val, text_val = (
            post.get("news_url"), post.get("source_name"), post.get("text")
        )
        url = url_val if isinstance(url_val, str) else None
        source_name = name_val if isinstance(name_val, str) else None
        summary = text_val if isinstance(text_val, str) else ""
        raw_tickers = post.get("tickers") or []
        tickers = tuple(
            str(t).upper() for t in raw_tickers if isinstance(t, str) and t.strip()
        ) if isinstance(raw_tickers, list) else ()
        sentiment = post.get("sentiment") if isinstance(post.get("sentiment"), str) else None
        event_id = str(post.get("event_id")) if post.get("event_id") is not None else None
        ident, provider_news_id = article_identity(
            post.get("news_id"), url, source_name, title, post.get("date")
        )
        articles.append(
            IngestArticle(
                id=ident, provider=source, provider_news_id=provider_news_id,
                published_at=published, title=title.strip(), url=url,
                source_name=source_name, summary=summary.strip(), tickers=tickers,
                sentiment=sentiment, event_id=event_id,
            )
        )
    return articles, rejects


def article_to_raw(article: IngestArticle, *, first_seen_at: datetime) -> NewsItemRaw:
    """Direct (Tier-1) shaping: article → untrusted NewsItemRaw. ``available_at``
    is left None (the settle adapter computes it)."""
    return NewsItemRaw(
        source=article.provider, source_id=article.id, url=article.url,
        title=article.title, summary=article.summary,
        published_at=article.published_at, discovered_at=ensure_utc(first_seen_at),
        available_at=None, assets=article.tickers,
    )


# --- real HTTP source (used by the Tier-2 poller) ----------------------------
class CryptoNewsApiAdapter(NewsSourceAdapter):
    """Real Crypto News API HTTP source (off by default; token never logged)."""

    def __init__(self, config: CryptoNewsConfig) -> None:
        if not config.token:
            raise ValueError("CryptoNewsApiAdapter requires a non-empty api token")
        if config.items <= 0 or config.max_pages <= 0:
            raise ValueError("items and max_pages must be > 0")
        self._cfg = config

    def _safe_params(self, page: int) -> dict[str, object]:
        """Request params for provenance/logs — WITHOUT the token."""
        return {
            "tickers": ",".join(self._cfg.tickers),
            "items": self._cfg.items,
            "page": page,
        }

    def fetch_result(self, *, now: datetime) -> FetchResult:
        """Poll the API across bounded pages. Raises token-free ``NewsSourceError``
        on any HTTP/network/parse/schema failure (never a valid-empty result)."""
        import httpx  # noqa: PLC0415 (intentional lazy import)

        all_articles: list[IngestArticle] = []
        all_rejects: list[tuple[str, str]] = []
        bodies: list[str] = []
        status: int | None = None
        for page in range(1, self._cfg.max_pages + 1):
            # Typed request params (httpx accepts str/int); token added last, never logged.
            params: dict[str, str | int] = {
                "tickers": ",".join(self._cfg.tickers), "items": self._cfg.items,
                "page": page, "token": self._cfg.token,
            }
            try:
                # Suppress httpx's URL log so the token (a query param) never reaches
                # a log record, even without app-level redaction (defense in depth).
                with _no_httpx_request_log():
                    resp = httpx.get(
                        self._cfg.base_url, params=params, timeout=self._cfg.timeout_seconds
                    )
                status = resp.status_code
                resp.raise_for_status()
                bodies.append(resp.text)
                payload = resp.json()
            except httpx.HTTPStatusError as exc:
                # Token-free: only the status code, never the URL/params/body.
                raise NewsSourceError(
                    f"Crypto News API returned HTTP {exc.response.status_code}"
                ) from None
            except Exception:  # timeout/DNS/TLS/JSON/network — token-free message
                raise NewsSourceError("Crypto News API request failed") from None
            articles, rejects = parse_cryptonews_payload(payload, source=self._cfg.source)
            all_articles.extend(articles)
            all_rejects.extend(rejects)
            if not articles:  # empty page → stop paginating (OK_EMPTY)
                break
        response_hash = (
            hashlib.sha256("".join(bodies).encode("utf-8")).hexdigest() if bodies else None
        )
        return FetchResult(
            articles=all_articles, http_status=status, response_hash=response_hash,
            request_params=self._safe_params(1), rejects=all_rejects,
        )

    def fetch(self, *, now: datetime, since: datetime | None = None) -> list[NewsItemRaw]:
        """Direct (Tier-1) read: shape freshly-fetched articles with
        ``discovered_at = now``. Tier-2 uses ``fetch_result`` + the store instead."""
        result = self.fetch_result(now=now)
        return [article_to_raw(a, first_seen_at=now) for a in result.articles]


# --- decision-time read path (store-backed; no boundary network I/O) ---------
class IngestionStoreNewsAdapter(NewsSourceAdapter):
    """Reads first_seen_at from the isolated ingestion store (no network). This is
    what the P9 runner uses at the boundary; wrap it with the settle adapter."""

    def __init__(self, store: NewsIngestionStore, *, lookback_hours: int = 24) -> None:
        self._store = store
        self._lookback_hours = lookback_hours

    def fetch(self, *, now: datetime, since: datetime | None = None) -> list[NewsItemRaw]:
        return self._store.read_raw(now=now, since=since, lookback_hours=self._lookback_hours)
