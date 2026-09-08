"""Tier-2 news ingestion store (Phase 9 — Crypto News API; additive, isolated).

Continuous news ingestion is decoupled from decision-making so P9 has a
DEFENSIBLE, auditable ``first_seen_at`` (when *we* first observed an article),
independent of the decision boundary — the no-look-ahead evidence the boundary
adapter needs.

* A lightweight poller (``scripts/run_news_ingest``) fetches Crypto News API on a
  15-minute cadence and UPSERTs each article here. ``first_seen_at`` is written
  ONCE (on first observation) and never moved; ``fetched_at`` is refreshed on each
  poll that re-sees the article. Full ingestion provenance is preserved
  (provider, request metadata, HTTP status, response hash) WITHOUT touching the
  frozen P5/P6 ``NewsItem``/operational schema.
* The decision-time read path (``IngestionStoreNewsAdapter``) reads from this
  store and performs NO boundary network I/O — deterministic and restart-safe.

Isolation: this store uses its OWN ``DeclarativeBase`` and its OWN SQLite file
(``news_ingest_db_path``), so it never alters the frozen operational schema (it is
NOT registered on ``app.models.Base``) and is global (provider-wide, spanning runs
— first-seen is a property of our observation, not of any single run).
"""

from __future__ import annotations

import fcntl
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import DateTime, Integer, String, Text, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.database import make_engine, make_session_factory
from app.news.models import NewsItemRaw
from app.time_utils import ensure_utc, utc_now


class NewsIngestBase(DeclarativeBase):
    """Declarative base for the ISOLATED news-ingestion store (not app.models.Base)."""


class NewsIngestRecord(NewsIngestBase):
    """One ingested article + its ingestion provenance (Tier-2, §K)."""

    __tablename__ = "news_ingest"

    # Stable article identity: news_id → canonical-url hash → deterministic fingerprint.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_news_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # first_seen_at: written ONCE on first observation; never moved (no-look-ahead).
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tickers: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # json list
    sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Ingestion provenance (token-free): what fetch produced this row.
    request_params: Mapped[str] = mapped_column(  # json, never the token
        Text, nullable=False, default="{}"
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


@dataclass(frozen=True)
class UpsertStats:
    inserted: int
    updated: int


def _tune_sqlite(engine) -> None:  # noqa: ANN001
    """WAL + busy_timeout so the runner's read never blocks the poller's write."""

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _rec):  # noqa: ANN001, ANN202
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def acquire_ingest_lock(lock_path: str):  # noqa: ANN201 (returns an open handle | None)
    """Acquire an exclusive, non-blocking OS lock for single-instance ingestion.

    Returns the open file handle (keep it to hold the lock) or ``None`` if another
    live poller already holds it — the caller then exits WITHOUT any API call. A
    crashed holder's ``flock`` is auto-released by the OS, so a stale process never
    permanently blocks a future start; a normal shutdown releases it explicitly."""
    path = Path(lock_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")  # noqa: SIM115 (handle intentionally kept open)
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def release_ingest_lock(handle) -> None:  # noqa: ANN001
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def make_news_ingest_store(db_path: str) -> NewsIngestionStore:
    """Open (creating if needed) the isolated ingestion store at ``db_path``."""
    engine = make_engine(f"sqlite:///{db_path}")
    _tune_sqlite(engine)
    NewsIngestBase.metadata.create_all(engine)  # only the news_ingest table
    return NewsIngestionStore(make_session_factory(engine))


class NewsIngestionStore:
    """Read/write access to the ingestion store (deterministic; no network)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def upsert_articles(
        self,
        articles: list[IngestArticle],
        *,
        fetched_at: datetime,
        http_status: int | None,
        response_hash: str | None,
        request_params: dict[str, object],
    ) -> UpsertStats:
        """Insert new articles (setting ``first_seen_at=fetched_at``) and refresh the
        ``fetched_at``/provenance of ones already seen. ``first_seen_at`` is NEVER
        moved once set. ``request_params`` MUST already be token-free."""
        fetched_at = ensure_utc(fetched_at)
        params_json = json.dumps(request_params, sort_keys=True)
        inserted = updated = 0
        session = self._sf()
        try:
            for art in articles:
                row = session.get(NewsIngestRecord, art.id)
                if row is None:
                    session.add(
                        NewsIngestRecord(
                            id=art.id, provider=art.provider,
                            provider_news_id=art.provider_news_id,
                            published_at=ensure_utc(art.published_at),
                            first_seen_at=fetched_at, fetched_at=fetched_at,
                            title=art.title, url=art.url, source_name=art.source_name,
                            summary=art.summary, tickers=json.dumps(list(art.tickers)),
                            sentiment=art.sentiment, event_id=art.event_id,
                            request_params=params_json, http_status=http_status,
                            response_hash=response_hash,
                        )
                    )
                    inserted += 1
                else:
                    # first_seen_at stays; refresh only last-fetch provenance.
                    row.fetched_at = fetched_at
                    row.http_status = http_status
                    row.response_hash = response_hash
                    row.request_params = params_json
                    updated += 1
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return UpsertStats(inserted=inserted, updated=updated)

    def read_raw(
        self, *, now: datetime, since: datetime | None = None, lookback_hours: int = 24
    ) -> list[NewsItemRaw]:
        """Return articles observed by ``now`` as untrusted ``NewsItemRaw`` for the
        frozen P5 pipeline. No-look-ahead: only rows with ``first_seen_at <= now``
        and ``published_at >= now - lookback`` (bounded window). ``discovered_at`` is
        the persisted ``first_seen_at``; ``available_at`` is left None (the settle
        adapter computes it as ``max(published+settle, first_seen)``)."""
        now = ensure_utc(now)
        floor = now - timedelta(hours=lookback_hours)
        if since is not None:
            floor = max(floor, ensure_utc(since))
        session = self._sf()
        try:
            rows = session.scalars(
                select(NewsIngestRecord)
                .where(NewsIngestRecord.first_seen_at <= now)
                .where(NewsIngestRecord.published_at >= floor)
                .order_by(NewsIngestRecord.published_at)
            ).all()
            out: list[NewsItemRaw] = []
            for r in rows:
                out.append(
                    NewsItemRaw(
                        source=r.provider,
                        source_id=r.id,
                        url=r.url,
                        title=r.title,
                        summary=r.summary,
                        published_at=ensure_utc(r.published_at),
                        discovered_at=ensure_utc(r.first_seen_at),
                        available_at=None,  # settle adapter sets max(published+settle, first_seen)
                        assets=tuple(json.loads(r.tickers)),
                    )
                )
            return out
        finally:
            session.close()


@dataclass(frozen=True)
class IngestArticle:
    """A normalized Crypto News API article ready for the ingestion store."""

    id: str
    provider: str
    provider_news_id: str | None
    published_at: datetime
    title: str
    url: str | None
    source_name: str | None
    summary: str
    tickers: tuple[str, ...]
    sentiment: str | None
    event_id: str | None


# Late import avoidance: IngestArticle is referenced above via annotations only.
