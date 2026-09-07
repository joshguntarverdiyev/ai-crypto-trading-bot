"""Crypto News API adapter + Tier-2 ingestion — offline suite (Phase 9).

No real network: HTTP paths monkeypatch ``httpx.get``; timestamp/gate/store logic
is exercised on controlled inputs (never fed to a real run). Covers the 28
required cases: converter, timestamp/DST, failure semantics, dedup, availability
gate, provenance, and "token never logged".
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.exceptions import NewsSourceError
from app.news.config import NewsConfig
from app.news.cryptonews_adapter import (
    CryptoNewsApiAdapter,
    CryptoNewsConfig,
    IngestionStoreNewsAdapter,
    article_identity,
    parse_cryptonews_date,
    parse_cryptonews_payload,
)
from app.news.ingestion import IngestArticle, make_news_ingest_store
from app.news.service import NewsService
from app.paper.news_adapter import SettleMarginNewsAdapter

TOKEN = "SECRET-TOKEN-DO-NOT-LOG-abc123"


# --- helpers -----------------------------------------------------------------
class FakeResp:
    def __init__(self, status_code=200, json_data=None, text="", raise_status=False):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text
        self._raise = raise_status

    def raise_for_status(self):
        if self._raise:
            req = httpx.Request("GET", "https://cryptonews-api.com/api/v1")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError("err", request=req, response=resp)

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


def _cfg(**kw) -> CryptoNewsConfig:
    return CryptoNewsConfig(token=TOKEN, **kw)


def _post(news_id="n1", date="Mon, 08 Sep 2025 10:30:00 -0400", title="BTC rallies",
          url="https://x/y", tickers=("BTC",), source_name="CoinX", text="body"):
    p = {"title": title, "news_url": url, "date": date,
         "tickers": list(tickers), "source_name": source_name, "text": text}
    if news_id is not None:
        p["news_id"] = news_id
    return p


def _payload(*posts):
    return {"data": list(posts)}


def _store(tmp_path):
    return make_news_ingest_store(f"{tmp_path}/news_ingest.db")


def _article(**kw):
    base = dict(
        id="id1", provider="cryptonewsapi", provider_news_id="n1",
        published_at=datetime(2025, 9, 8, 14, 30, tzinfo=UTC), title="BTC rallies",
        url="https://x/y", source_name="CoinX", summary="body", tickers=("BTC",),
        sentiment="Positive", event_id=None,
    )
    base.update(kw)
    return IngestArticle(**base)


# --- 1-5 converter / filtering / pagination ----------------------------------
def test_01_valid_response_ok_items(monkeypatch) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResp(200, _payload(_post()), "b"))
    res = CryptoNewsApiAdapter(_cfg()).fetch_result(now=datetime.now(UTC))
    assert len(res.articles) == 1 and res.http_status == 200
    assert res.articles[0].tickers == ("BTC",)


def test_02_btc_filtering() -> None:
    arts, _ = parse_cryptonews_payload(_payload(_post(tickers=("BTC",))))
    assert arts[0].tickers == ("BTC",)


def test_03_eth_filtering() -> None:
    arts, _ = parse_cryptonews_payload(_payload(_post(tickers=("ETH",))))
    assert arts[0].tickers == ("ETH",)


def test_04_multiple_tickers() -> None:
    arts, _ = parse_cryptonews_payload(_payload(_post(tickers=("BTC", "ETH"))))
    assert arts[0].tickers == ("BTC", "ETH")


def test_05_pagination_merges_until_empty(monkeypatch) -> None:
    pages = [FakeResp(200, _payload(_post(news_id="a")), "b1"),
             FakeResp(200, _payload(), "b2")]  # second page empty → stop
    calls = {"i": 0}

    def fake_get(*a, **k):
        r = pages[calls["i"]]
        calls["i"] += 1
        return r

    monkeypatch.setattr("httpx.get", fake_get)
    res = CryptoNewsApiAdapter(_cfg(max_pages=3)).fetch_result(now=datetime.now(UTC))
    assert len(res.articles) == 1 and calls["i"] == 2  # stopped after empty page


# --- 6-7 deduplication -------------------------------------------------------
def test_06_duplicate_news_id_same_identity(tmp_path) -> None:
    id_a, _ = article_identity("n1", "https://x/y", "CoinX", "t", "d")
    id_b, _ = article_identity("n1", "https://z/w", "CoinY", "t2", "d2")
    assert id_a == id_b  # identity driven by news_id, not url/title
    store = _store(tmp_path)
    arts = [_article(id=id_a), _article(id=id_b)]
    s1 = store.upsert_articles(arts, fetched_at=datetime.now(UTC), http_status=200,
                               response_hash="h", request_params={})
    assert s1.inserted == 1 and s1.updated == 1  # collapsed to one row


def test_07_duplicate_canonical_url_same_identity() -> None:
    id1, nid1 = article_identity(None, "https://x/y/", "CoinX", "t", "d")
    id2, nid2 = article_identity(None, "https://x/y?utm=1#frag", "CoinY", "t2", "d2")
    assert id1 == id2 and nid1 is None  # canonical url collapses query/fragment/slash


# --- 8-10 malformed / missing / bad-date ------------------------------------
def test_08_invalid_json_raises(monkeypatch) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResp(200, ValueError("bad json"), "x"))
    with pytest.raises(NewsSourceError):
        CryptoNewsApiAdapter(_cfg()).fetch_result(now=datetime.now(UTC))


def test_09_missing_title_rejected() -> None:
    arts, rejects = parse_cryptonews_payload(_payload(_post(title="")))
    assert arts == [] and any(r[0] == "missing_title" for r in rejects)


def test_10_invalid_date_rejected_no_fabrication() -> None:
    arts, rejects = parse_cryptonews_payload(_payload(_post(date="not-a-date")))
    assert arts == [] and any(r[0] == "invalid_date" for r in rejects)


# --- 11-12 timestamp / DST ---------------------------------------------------
def test_11_gmt_minus_0400_to_utc() -> None:
    dt = parse_cryptonews_date("Mon, 08 Sep 2025 10:30:00 -0400")
    assert dt == datetime(2025, 9, 8, 14, 30, tzinfo=UTC)  # +4h → UTC


def test_12_dst_sensitive_offsets() -> None:
    edt = parse_cryptonews_date("Wed, 20 Jul 2022 10:30:00 -0400")  # EDT summer
    est = parse_cryptonews_date("Fri, 20 Jan 2023 10:30:00 -0500")  # EST winter
    assert edt == datetime(2022, 7, 20, 14, 30, tzinfo=UTC)
    assert est == datetime(2023, 1, 20, 15, 30, tzinfo=UTC)  # same wall clock, different UTC


def test_12b_naive_date_rejected() -> None:
    assert parse_cryptonews_date("Mon, 08 Sep 2025 10:30:00") is None  # no offset → reject


# --- 13 first_seen_at persistence -------------------------------------------
def test_13_first_seen_at_is_immutable(tmp_path) -> None:
    store = _store(tmp_path)
    t0 = datetime(2025, 9, 8, 12, 0, tzinfo=UTC)
    store.upsert_articles([_article()], fetched_at=t0, http_status=200,
                          response_hash="h", request_params={})
    t1 = t0 + timedelta(hours=1)
    stats = store.upsert_articles([_article()], fetched_at=t1, http_status=200,
                                  response_hash="h2", request_params={})
    assert stats.inserted == 0 and stats.updated == 1
    raw = store.read_raw(now=t1 + timedelta(hours=1), lookback_hours=48)
    assert raw[0].discovered_at == t0  # first_seen_at preserved despite later fetch


# --- 14-15 settle margin + availability formula ------------------------------
def test_14_settle_margin_120s(tmp_path) -> None:
    store = _store(tmp_path)
    pub = datetime(2025, 9, 8, 12, 0, tzinfo=UTC)
    store.upsert_articles([_article(published_at=pub)], fetched_at=pub, http_status=200,
                          response_hash="h", request_params={})
    inner = IngestionStoreNewsAdapter(store, lookback_hours=48)
    out = SettleMarginNewsAdapter(inner, settle_seconds=120).fetch(now=pub + timedelta(hours=1))
    # first_seen == pub, so available = max(pub+120, pub) = pub+120
    assert out[0].available_at == pub + timedelta(seconds=120)


def test_15_available_at_is_max_of_settle_and_first_seen(tmp_path) -> None:
    store = _store(tmp_path)
    pub = datetime(2025, 9, 8, 12, 0, tzinfo=UTC)
    first_seen = pub + timedelta(minutes=30)  # we saw it well after publish
    store.upsert_articles([_article(published_at=pub)], fetched_at=first_seen,
                          http_status=200, response_hash="h", request_params={})
    inner = IngestionStoreNewsAdapter(store, lookback_hours=48)
    settle = SettleMarginNewsAdapter(inner, settle_seconds=120)
    out = settle.fetch(now=first_seen + timedelta(hours=1))
    # max(pub+120s, pub+30m) = pub+30m (first_seen dominates)
    assert out[0].available_at == first_seen


# --- 16-18 gate: cutoff / future / stale -------------------------------------
def _service(store, settle=120):
    return NewsService(
        SettleMarginNewsAdapter(IngestionStoreNewsAdapter(store, lookback_hours=48),
                                settle_seconds=settle),
        NewsConfig(),
    )


def test_16_decision_time_cutoff_admits_in_gate(tmp_path) -> None:
    store = _store(tmp_path)
    pub = datetime(2025, 9, 8, 12, 0, tzinfo=UTC)
    store.upsert_articles([_article(published_at=pub)], fetched_at=pub, http_status=200,
                          response_hash="h", request_params={})
    dt = pub + timedelta(hours=1)
    ctx = _service(store).build_context(decision_time=dt, now=dt)
    assert len(ctx.items) == 1 and ctx.items[0].available_at <= ctx.decision_time


def test_17_future_availability_excluded(tmp_path) -> None:
    store = _store(tmp_path)
    pub = datetime(2025, 9, 8, 12, 0, tzinfo=UTC)
    store.upsert_articles([_article(published_at=pub)], fetched_at=pub, http_status=200,
                          response_hash="h", request_params={})
    # decision_time BEFORE available_at (pub+120s) → excluded as future
    dt = pub + timedelta(seconds=60)
    ctx = _service(store).build_context(decision_time=dt, now=pub + timedelta(hours=1))
    assert ctx.items == () and any(i.code.name == "FUTURE_AVAILABILITY" for i in ctx.issues)


def test_18_stale_excluded(tmp_path) -> None:
    store = _store(tmp_path)
    pub = datetime(2025, 9, 8, 12, 0, tzinfo=UTC)
    store.upsert_articles([_article(published_at=pub)], fetched_at=pub, http_status=200,
                          response_hash="h", request_params={})
    dt = pub + timedelta(hours=48)  # older than max_news_age (24h)
    ctx = _service(store).build_context(decision_time=dt, now=dt)
    assert ctx.items == () and any(i.code.name == "STALE" for i in ctx.issues)


# --- 19-23 HTTP / transport failure semantics --------------------------------
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_19_to_21_http_errors_raise(monkeypatch, status) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResp(status, {}, "x", raise_status=True))
    with pytest.raises(NewsSourceError) as ei:
        CryptoNewsApiAdapter(_cfg()).fetch_result(now=datetime.now(UTC))
    assert str(status) in str(ei.value) and TOKEN not in str(ei.value)


def test_22_timeout_raises(monkeypatch) -> None:
    def boom(*a, **k):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("httpx.get", boom)
    with pytest.raises(NewsSourceError) as ei:
        CryptoNewsApiAdapter(_cfg()).fetch_result(now=datetime.now(UTC))
    assert TOKEN not in str(ei.value)


def test_23_network_failure_raises(monkeypatch) -> None:
    def boom(*a, **k):
        raise httpx.ConnectError("dns/tls fail")

    monkeypatch.setattr("httpx.get", boom)
    with pytest.raises(NewsSourceError) as ei:
        CryptoNewsApiAdapter(_cfg()).fetch_result(now=datetime.now(UTC))
    assert TOKEN not in str(ei.value)


# --- 24 empty valid response -------------------------------------------------
def test_24_empty_valid_response_ok_empty(monkeypatch) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResp(200, _payload(), "b"))
    res = CryptoNewsApiAdapter(_cfg()).fetch_result(now=datetime.now(UTC))
    assert res.articles == [] and res.http_status == 200  # OK_EMPTY, not a failure


# --- 25 token never in logs/errors/provenance --------------------------------
def test_25_token_never_in_error_or_provenance(monkeypatch) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResp(403, {}, "x", raise_status=True))
    with pytest.raises(NewsSourceError) as ei:
        CryptoNewsApiAdapter(_cfg()).fetch_result(now=datetime.now(UTC))
    assert TOKEN not in str(ei.value) and TOKEN not in repr(ei.value)
    # provenance params never carry the token
    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResp(200, _payload(_post()), "b"))
    res = CryptoNewsApiAdapter(_cfg()).fetch_result(now=datetime.now(UTC))
    assert "token" not in res.request_params
    assert TOKEN not in str(res.request_params)


def test_25b_token_registered_for_redaction() -> None:
    from app.config import load_settings

    s = load_settings(_env_file=None, crypto_news_api_token=TOKEN)
    assert TOKEN in s.secret_values()  # global log redactor scrubs it


# --- 26 provenance -----------------------------------------------------------
def test_26_provenance_persisted(tmp_path) -> None:
    from sqlalchemy import select

    from app.database import session_scope
    from app.news.ingestion import NewsIngestRecord

    store = _store(tmp_path)
    t = datetime(2025, 9, 8, 12, 0, tzinfo=UTC)
    store.upsert_articles(
        [_article()], fetched_at=t, http_status=200, response_hash="abc123hash",
        request_params={"tickers": "BTC,ETH", "page": 1},
    )
    with session_scope(store._sf) as sess:
        row = sess.scalars(select(NewsIngestRecord)).first()
        assert row.http_status == 200 and row.response_hash == "abc123hash"
        assert row.source_name == "CoinX" and row.url == "https://x/y"
        assert row.first_seen_at is not None and row.fetched_at is not None
        assert "token" not in row.request_params


# --- 27 deterministic repeated ingestion -------------------------------------
def test_27_repeated_ingestion_is_deterministic(tmp_path) -> None:
    store = _store(tmp_path)
    t = datetime(2025, 9, 8, 12, 0, tzinfo=UTC)
    arts, _ = parse_cryptonews_payload(_payload(_post(news_id="a"), _post(news_id="b", url="https://p/q")))
    ids1 = [a.id for a in arts]
    arts2, _ = parse_cryptonews_payload(_payload(_post(news_id="a"), _post(news_id="b", url="https://p/q")))
    assert ids1 == [a.id for a in arts2]  # stable identities
    store.upsert_articles(arts, fetched_at=t, http_status=200, response_hash="h", request_params={})
    s2 = store.upsert_articles(arts2, fetched_at=t + timedelta(minutes=15), http_status=200,
                               response_hash="h", request_params={})
    assert s2.inserted == 0 and s2.updated == 2  # re-ingest = all updates, no dups


# --- 29 real observed live schema (regression fixture) -----------------------
# Mirrors the SHAPE of a real Crypto News API trial response verified 2026-09-07:
# envelope {data, total_items, total_pages}; articles carry date (RFC-2822 with an
# explicit -0400 offset), news_url, title, source_name, tickers, text, sentiment,
# topics, type, image_url — and DO NOT carry news_id or event_id. Identity must
# therefore fall back to the canonical-URL hash, and the extra envelope keys must be
# ignored. This pins the observed schema so future drift is caught offline.
_REAL_SHAPE_PAYLOAD = {
    "data": [
        {"date": "Mon, 07 Sep 2026 18:07:16 -0400", "news_url": "https://example.com/a",
         "title": "Headline A", "source_name": "CryptoSlate", "text": "body A",
         "tickers": ["BTC"], "sentiment": "Positive", "topics": [], "type": "Article",
         "image_url": "https://img/a.png"},
        {"date": "Mon, 07 Sep 2026 18:05:41 -0400", "news_url": "https://example.com/b",
         "title": "Headline B", "source_name": "Bitcoin", "text": "body B",
         "tickers": ["BTC", "LINK"], "sentiment": "Neutral", "topics": [], "type": "Article",
         "image_url": "https://img/b.png"},
    ],
    "total_items": 2,
    "total_pages": 1,
}


def test_29_real_observed_schema(tmp_path) -> None:
    arts, rejects = parse_cryptonews_payload(_REAL_SHAPE_PAYLOAD)
    assert rejects == [] and len(arts) == 2
    a0 = arts[0]
    # RFC-2822 -0400 (EDT) → UTC (+4h), DST-honored
    assert a0.published_at == datetime(2026, 9, 7, 22, 7, 16, tzinfo=UTC)
    # news_id / event_id absent → URL-hash identity, no provider_news_id
    assert a0.provider_news_id is None and len(a0.id) == 40
    assert arts[1].provider_news_id is None and arts[0].id != arts[1].id
    # tickers preserved at raw/store layer (known-asset filtering happens in P5 normalize)
    assert arts[1].tickers == ("BTC", "LINK")
    # extra envelope keys (total_items/total_pages) are ignored, not errors
    # store round-trip: first_seen_at set once; settle sets available_at
    store = _store(tmp_path)
    t0 = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    store.upsert_articles(arts, fetched_at=t0, http_status=200, response_hash="h",
                          request_params={"tickers": "BTC,ETH", "items": 3, "page": 1})
    raw = IngestionStoreNewsAdapter(store, lookback_hours=72).fetch(now=t0 + timedelta(hours=1))
    assert len(raw) == 2 and all(r.discovered_at == t0 for r in raw)


# --- 30 token never reaches HTTP client logs (even without app redaction) ----
def test_30_token_never_in_httpx_logs_without_app_redaction(monkeypatch) -> None:
    """Proves the hardening: httpx's own request-URL log (which contains the token
    query param) is suppressed by the adapter itself, so the token cannot leak to a
    log record even if the application's redaction (configure_logging) is NOT set up."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    prev_root = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    httpx_logger = logging.getLogger("httpx")
    prev_httpx = httpx_logger.level
    httpx_logger.setLevel(logging.INFO)  # simulate httpx's default request logging ON
    try:
        def fake_get(url, **kw):
            # emulate httpx emitting the full URL (with token) at INFO during the call
            tok = kw.get("params", {}).get("token", "")
            logging.getLogger("httpx").info(f'HTTP Request: GET {url}?token={tok} "200 OK"')
            return FakeResp(200, _payload(_post()), "b")

        monkeypatch.setattr("httpx.get", fake_get)
        res = CryptoNewsApiAdapter(_cfg()).fetch_result(now=datetime.now(UTC))
        logs = buf.getvalue()
        assert TOKEN not in logs  # suppressed at the httpx-logger level during the request
        assert res.http_status == 200 and len(res.articles) == 1  # request still worked
        # httpx logger level restored to its prior value after the call
        assert httpx_logger.level == logging.INFO
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_root)
        httpx_logger.setLevel(prev_httpx)


def test_31_token_absent_from_error_logs(monkeypatch) -> None:
    """On an HTTP error the token must not appear in the raised message or any log."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    root = logging.getLogger()
    root.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.INFO)
    try:
        def fake_get(url, **kw):
            tok = kw.get("params", {}).get("token", "")
            logging.getLogger("httpx").info(f'HTTP Request: GET {url}?token={tok} "403"')
            return FakeResp(403, {}, "x", raise_status=True)

        monkeypatch.setattr("httpx.get", fake_get)
        with pytest.raises(NewsSourceError) as ei:
            CryptoNewsApiAdapter(_cfg()).fetch_result(now=datetime.now(UTC))
        assert TOKEN not in str(ei.value) and TOKEN not in buf.getvalue()
    finally:
        root.removeHandler(handler)


# --- 28 no-look-ahead --------------------------------------------------------
def test_28_no_look_ahead_first_seen_in_future_excluded(tmp_path) -> None:
    store = _store(tmp_path)
    pub = datetime(2025, 9, 8, 12, 0, tzinfo=UTC)
    future_seen = datetime(2025, 9, 8, 18, 0, tzinfo=UTC)
    store.upsert_articles([_article(published_at=pub)], fetched_at=future_seen,
                          http_status=200, response_hash="h", request_params={})
    # read as of a time BEFORE we first saw it → must not appear
    raw = store.read_raw(now=datetime(2025, 9, 8, 15, 0, tzinfo=UTC), lookback_hours=48)
    assert raw == []
    # once now >= first_seen, it is visible
    raw2 = store.read_raw(now=future_seen + timedelta(minutes=1), lookback_hours=48)
    assert len(raw2) == 1
