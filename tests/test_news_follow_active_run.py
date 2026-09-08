"""P9: news poller --follow-active-run auto-discovery (offline, fail-closed).

The poller discovers the UNIQUE active paper run (status='running' + fresh heartbeat)
and binds ONLY to its FROZEN T0 universe via the unchanged load_frozen_universe path.
No active / ambiguous / stale run ⇒ ZERO API calls (no lock, no adapter).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.database import session_scope
from app.market_data.models import Symbol
from app.models import PaperTradingRunRecord
from app.news.cryptonews_adapter import FetchResult
from app.paper.universe_build import build_and_persist_universe
from app.time_utils import utc_now
from app.universe.models import MarketInfo
from app.universe.provider import FixtureUniverseProvider
from tests._p9_helpers import build_paper, main_factory, paper_settings

T0 = datetime(2026, 9, 8, tzinfo=UTC)
STALE = timedelta(days=100)


def _mkt(sym, vol):
    s = Symbol.parse(sym)
    return MarketInfo(symbol=s, base=s.base, quote="USDT", active=True,
                      quote_volume_24h=Decimal(str(vol)))


class _RecordingAdapter:
    """Stub CryptoNewsApiAdapter: records the tickers it was configured with; no network."""

    last_tickers: tuple = ()

    def __init__(self, cfg):
        _RecordingAdapter.last_tickers = cfg.tickers

    def fetch_result(self, *, now):
        return FetchResult(articles=[], http_status=200, response_hash=None, request_params={})


def _settings(tmp_path, **overrides):
    return paper_settings(
        tmp_path, paper_universe_min_quote_volume=Decimal("0"), crypto_news_api_token="X",
        news_ingest_db_path=f"{tmp_path}/news_ingest.db", **overrides,
    )


def _run_with_universe(tmp_path, main_sf, settings, markets):
    runner, run_id, main_sf, _ = build_paper(tmp_path, settings=settings, main_sf=main_sf)
    build_and_persist_universe(runner._sf, run_id, provider=FixtureUniverseProvider(markets),
                               cfg=settings.paper_validation_config(), now=T0)
    return run_id


def _forbid_calls(monkeypatch):
    from scripts import run_news_ingest
    monkeypatch.setattr(run_news_ingest, "CryptoNewsApiAdapter",
                        lambda *a, **k: pytest.fail("adapter must not be built on fail-closed"))
    monkeypatch.setattr(run_news_ingest, "acquire_ingest_lock",
                        lambda *a, **k: pytest.fail("lock must not be acquired on fail-closed"))
    monkeypatch.setattr("httpx.get", lambda *a, **k: pytest.fail("no API call on fail-closed"))


# --- active run present → bind to its FROZEN universe (ignore MARKET_SYMBOLS) --------
def test_follow_active_run_binds_to_frozen_universe(tmp_path, monkeypatch) -> None:
    from scripts import run_news_ingest

    settings = _settings(tmp_path, market_symbols=["DOGE/USDT"])  # would-be fallback, ignored
    main_sf = main_factory(settings)
    _run_with_universe(tmp_path, main_sf, settings,
                       [_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800), _mkt("SOL/USDT", 700)])
    monkeypatch.setattr(run_news_ingest, "CryptoNewsApiAdapter", _RecordingAdapter)
    monkeypatch.setattr("httpx.get", lambda *a, **k: pytest.fail("store-backed; no network"))
    rc = run_news_ingest.run(settings, iterations=1, supervise=False, follow_active_run=True)
    assert rc == 0
    assert _RecordingAdapter.last_tickers == ("BTC", "ETH", "SOL")  # frozen universe, NOT DOGE


# --- no active run → fail-closed, ZERO API calls, no lock ----------------------------
def test_follow_no_active_run_fails_closed_zero_calls(tmp_path, monkeypatch) -> None:
    from scripts import run_news_ingest

    settings = _settings(tmp_path)
    main_factory(settings)  # empty catalog
    _forbid_calls(monkeypatch)
    rc = run_news_ingest.run(settings, iterations=1, supervise=False, follow_active_run=True)
    assert rc == 1


# --- ambiguous (2 running+fresh) → fail-closed, ZERO API calls -----------------------
def test_follow_ambiguous_fails_closed_zero_calls(tmp_path, monkeypatch) -> None:
    from scripts import run_news_ingest

    settings = _settings(tmp_path)
    main_sf = main_factory(settings)
    _run_with_universe(tmp_path, main_sf, settings, [_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800)])
    _run_with_universe(tmp_path, main_sf, settings, [_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800)])
    _forbid_calls(monkeypatch)
    rc = run_news_ingest.run(settings, iterations=1, supervise=False, follow_active_run=True)
    assert rc == 1


# --- running but STALE heartbeat → fail-closed, ZERO API calls -----------------------
def test_follow_stale_run_fails_closed_zero_calls(tmp_path, monkeypatch) -> None:
    from scripts import run_news_ingest

    settings = _settings(tmp_path)
    main_sf = main_factory(settings)
    run_id = _run_with_universe(tmp_path, main_sf, settings,
                                [_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800)])
    with session_scope(main_sf) as s:
        s.get(PaperTradingRunRecord, run_id).heartbeat_at = utc_now() - STALE
    _forbid_calls(monkeypatch)
    rc = run_news_ingest.run(settings, iterations=1, supervise=False, follow_active_run=True)
    assert rc == 1


# --- --paper-run-id and --follow-active-run are mutually exclusive -------------------
def test_cli_mutually_exclusive(monkeypatch) -> None:
    from scripts import run_news_ingest

    monkeypatch.setattr("sys.argv",
                        ["run_news_ingest", "--paper-run-id", "x", "--follow-active-run"])
    with pytest.raises(SystemExit):
        run_news_ingest.main()
