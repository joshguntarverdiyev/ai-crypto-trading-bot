"""News availability gate (§7): causal, anti-look-ahead, conservative."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.news.config import NewsConfig
from app.news.fixture_adapter import FixtureNewsAdapter
from app.news.models import NewsAvailability, NewsItemRaw
from app.news.service import NewsService

DT = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)  # decision_time
NOW = DT


def _svc(items: list[NewsItemRaw], cfg: NewsConfig | None = None) -> NewsService:
    return NewsService(FixtureNewsAdapter(items), cfg or NewsConfig())


def _raw(**kw) -> NewsItemRaw:
    base = dict(source="fixture", source_id=kw.get("source_id", "x"), title="t")
    base.update(kw)
    return NewsItemRaw(**base)


def test_known_available_and_fresh_is_usable() -> None:
    avail = DT - timedelta(hours=1)
    ctx = _svc([_raw(source_id="a", published_at=avail, available_at=avail)]).build_context(
        decision_time=DT, now=NOW
    )
    assert ctx.availability is NewsAvailability.AVAILABLE
    assert len(ctx.items) == 1


def test_future_availability_is_excluded_no_look_ahead() -> None:
    future = DT + timedelta(hours=1)
    ctx = _svc(
        [_raw(source_id="a", published_at=DT - timedelta(hours=1), available_at=future)]
    ).build_context(decision_time=DT, now=DT + timedelta(hours=2))
    assert ctx.items == ()
    assert ctx.availability is NewsAvailability.DEGRADED


def test_unknown_availability_excluded_when_required() -> None:
    ctx = _svc(
        [_raw(source_id="a", published_at=DT - timedelta(hours=1))]  # no available_at
    ).build_context(decision_time=DT, now=NOW)
    assert ctx.items == ()
    assert ctx.availability is NewsAvailability.DEGRADED


def test_unknown_availability_admitted_when_not_required() -> None:
    cfg = NewsConfig(require_known_availability=False)
    ctx = _svc(
        [_raw(source_id="a", published_at=DT - timedelta(hours=1))], cfg
    ).build_context(decision_time=DT, now=NOW)
    assert len(ctx.items) == 1
    assert ctx.items[0].trust == 0.5  # admitted but trust-lowered


def test_stale_beyond_max_age() -> None:
    old = DT - timedelta(days=3)
    ctx = _svc([_raw(source_id="a", published_at=old, available_at=old)]).build_context(
        decision_time=DT, now=NOW
    )
    assert ctx.availability is NewsAvailability.STALE
    assert ctx.items == ()


def test_empty_source_is_unavailable_not_clean() -> None:
    ctx = _svc([]).build_context(decision_time=DT, now=NOW)
    assert ctx.availability is NewsAvailability.UNAVAILABLE  # §0.1-3: not "no news = safe"


def test_deterministic() -> None:
    avail = DT - timedelta(hours=1)
    svc = _svc([_raw(source_id="a", published_at=avail, available_at=avail)])
    assert svc.build_context(decision_time=DT, now=NOW) == svc.build_context(
        decision_time=DT, now=NOW
    )
