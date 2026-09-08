"""P9: news poller binds to a paper run's FROZEN T0 universe (offline, fail-closed)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import make_engine, make_session_factory, session_scope
from app.exceptions import PaperRunError
from app.market_data.models import Symbol
from app.models import PaperTradingRunRecord, PaperUniverseRecord
from app.news.cryptonews_adapter import FetchResult
from app.paper.build import _effective_settings
from app.paper.store import run_db_path
from app.paper.universe_build import build_and_persist_universe, load_frozen_universe
from app.universe.models import MarketInfo
from app.universe.provider import FixtureUniverseProvider
from tests._p9_helpers import build_paper, paper_settings

T0 = datetime(2026, 9, 8, tzinfo=UTC)


def _mkt(sym, vol):
    s = Symbol.parse(sym)
    return MarketInfo(symbol=s, base=s.base, quote="USDT", active=True,
                      quote_volume_24h=Decimal(str(vol)))


def _run_with_universe(tmp_path, markets, *, history_ok=None):
    """Create a real P9 paper run and persist a frozen universe into its own DB."""
    settings = paper_settings(tmp_path, paper_universe_min_quote_volume=Decimal("0"))
    runner, run_id, main_sf, _s = build_paper(tmp_path, settings=settings)
    cfg = settings.paper_validation_config()
    sel = build_and_persist_universe(runner._sf, run_id, provider=FixtureUniverseProvider(markets),
                                     cfg=cfg, now=T0, history_ok=history_ok)
    return main_sf, run_id, sel, settings


def _run_sf_for(main_sf, run_id):  # test-only read-WRITE handle for injection
    with session_scope(main_sf) as s:
        db_path = s.get(PaperTradingRunRecord, run_id).db_path
    return make_session_factory(make_engine(f"sqlite:///{db_path}"))


class _RecordingAdapter:
    """Stub CryptoNewsApiAdapter: records the tickers it was configured with; no network."""

    last_tickers: tuple = ()

    def __init__(self, cfg):
        _RecordingAdapter.last_tickers = cfg.tickers

    def fetch_result(self, *, now):
        return FetchResult(articles=[], http_status=200, response_hash=None, request_params={})


# --- A/B/C. persisted universe: ordered symbols + hash preserved -------------------
def test_load_frozen_universe_ordered_symbols_and_hash(tmp_path) -> None:
    markets = [_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800), _mkt("SOL/USDT", 700),
               _mkt("XRP/USDT", 600), _mkt("PEPE/USDT", 500)]
    main_sf, run_id, sel, _s = _run_with_universe(tmp_path, markets)
    symbols, uni_hash = load_frozen_universe(main_sf, run_id)
    assert [str(s) for s in symbols] == \
        ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "PEPE/USDT"]  # B: exact order
    assert uni_hash == sel.selection_hash  # C: digest preserved + verified


# --- D/E/J. news config derives tickers + known_assets from the frozen universe -----
def test_news_config_derives_from_frozen_universe(tmp_path) -> None:
    markets = [_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800), _mkt("SOL/USDT", 700)]
    main_sf, run_id, _sel, settings = _run_with_universe(tmp_path, markets)
    symbols, _h = load_frozen_universe(main_sf, run_id)
    eff = _effective_settings(settings, symbols)
    assert eff.crypto_news_config().tickers == ("BTC", "ETH", "SOL")       # D
    assert set(eff.news_config().known_assets) >= {"BTC", "ETH", "SOL"}    # E
    assert eff.crypto_news_config().max_pages == 1                          # J: one global request


# --- G. unknown / missing run + universe → fail closed -----------------------------
def test_unknown_run_fails_closed(tmp_path) -> None:
    _r, _rid, main_sf, _s = build_paper(tmp_path, settings=paper_settings(tmp_path))
    with pytest.raises(PaperRunError, match="unknown paper run_id"):
        load_frozen_universe(main_sf, "does-not-exist")


def test_missing_run_db_fails_closed(tmp_path) -> None:
    main_sf, run_id, _sel, settings = _run_with_universe(
        tmp_path, [_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800)])
    run_db_path(settings.paper_validation_config(), run_id).unlink()  # delete run DB
    with pytest.raises(PaperRunError, match="run DB missing"):
        load_frozen_universe(main_sf, run_id)


def test_absent_universe_fails_closed(tmp_path) -> None:
    _r, run_id, main_sf, _s = build_paper(tmp_path, settings=paper_settings(tmp_path))
    with pytest.raises(PaperRunError, match="no frozen universe"):
        load_frozen_universe(main_sf, run_id)  # run exists, but no universe persisted


# --- I/N/O. replacement / inconsistent hash → fail closed; originals not mutated -----
def test_replacement_attempt_detected_fail_closed(tmp_path) -> None:
    main_sf, run_id, sel, _s = _run_with_universe(
        tmp_path, [_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800)])
    with session_scope(_run_sf_for(main_sf, run_id)) as s:  # inject a DIFFERENT-hash row
        s.add(PaperUniverseRecord(paper_run_id=run_id, selection_hash="deadbeef" * 8,
                                  symbol="SOL/USDT", rank=99, quote_volume_24h=Decimal("1"),
                                  selected_at=T0))
    with pytest.raises(PaperRunError, match="inconsistent frozen-universe hash"):
        load_frozen_universe(main_sf, run_id)
    # N: the original frozen rows are untouched
    with session_scope(_run_sf_for(main_sf, run_id)) as s:
        orig = {r.symbol for r in s.scalars(
            select(PaperUniverseRecord).where(
                PaperUniverseRecord.selection_hash == sel.selection_hash)).all()}
    assert orig == {"BTC/USDT", "ETH/USDT"}


# --- F. poller bound to a run uses the FROZEN universe tickers (no .env fallback) ---
def test_poller_bound_uses_frozen_universe_tickers(tmp_path, monkeypatch) -> None:
    from scripts import run_news_ingest

    main_sf, run_id, _sel, settings = _run_with_universe(
        tmp_path, [_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800), _mkt("SOL/USDT", 700)])
    # a DIFFERENT MARKET_SYMBOLS in settings would be ignored in favor of the frozen run
    settings = settings.model_copy(update={"market_symbols": ["DOGE/USDT"],
                                           "crypto_news_api_token": "X"})
    monkeypatch.setattr(run_news_ingest, "CryptoNewsApiAdapter", _RecordingAdapter)
    monkeypatch.setattr("httpx.get", lambda *a, **k: pytest.fail("store-backed; no network"))
    rc = run_news_ingest.run(settings, iterations=1, supervise=False, paper_run_id=run_id)
    assert rc == 0
    assert _RecordingAdapter.last_tickers == ("BTC", "ETH", "SOL")  # frozen universe, NOT DOGE


# --- F/G. explicit run that can't be resolved → fail closed, ZERO API calls ---------
def test_poller_unknown_run_fails_closed_zero_calls(tmp_path, monkeypatch) -> None:
    from scripts import run_news_ingest

    monkeypatch.setattr("httpx.get", lambda *a, **k: pytest.fail("no API call on fail-closed"))
    monkeypatch.setattr(run_news_ingest, "CryptoNewsApiAdapter",
                        lambda *a, **k: pytest.fail("adapter must not be built on fail-closed"))
    settings = paper_settings(tmp_path, crypto_news_api_token="X",
                              news_ingest_db_path=f"{tmp_path}/news_ingest.db")
    rc = run_news_ingest.run(settings, iterations=1, supervise=False, paper_run_id="unknown-run")
    assert rc == 1  # fail-closed, no fallback


# --- K. standalone (no paper_run_id) still derives tickers from config --------------
def test_poller_standalone_uses_config_tickers(tmp_path, monkeypatch) -> None:
    from scripts import run_news_ingest

    monkeypatch.setattr(run_news_ingest, "CryptoNewsApiAdapter", _RecordingAdapter)
    monkeypatch.setattr("httpx.get", lambda *a, **k: pytest.fail("stub; no network"))
    settings = paper_settings(tmp_path, crypto_news_api_token="X",
                              market_symbols=["BTC/USDT", "ETH/USDT"],
                              news_ingest_db_path=f"{tmp_path}/news_ingest.db")
    rc = run_news_ingest.run(settings, iterations=1, supervise=False, paper_run_id=None)
    assert rc == 0
    assert _RecordingAdapter.last_tickers == ("BTC", "ETH")  # standalone from MARKET_SYMBOLS
