"""P9 startup orchestration: one T0 selection → persist → build (offline, fail-closed)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.ai.fixture_provider import FixtureAnalystProvider
from app.database import session_scope
from app.exceptions import PaperRunError
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.models import RawCandle, Symbol, Timeframe
from app.models import PaperUniverseRecord
from app.paper.build import start_paper_system
from app.paper.universe_build import load_frozen_universe
from app.universe.models import MarketInfo
from app.universe.provider import FixtureUniverseProvider
from tests._p9_helpers import APPROVE, main_factory, news_adapter, paper_settings

T0 = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _mkt(sym, vol):
    s = Symbol.parse(sym)
    return MarketInfo(symbol=s, base=s.base, quote="USDT", active=True,
                      quote_volume_24h=Decimal(str(vol)))


def _candles(symbol: str, tf: Timeframe, count: int = 320, end: datetime = T0):
    """Contiguous, closed, valid OHLCV ending at ``end`` (enough for the warmup screen)."""
    delta = tf.delta
    out: list[RawCandle] = []
    price = Decimal("100")
    for i in range(count):
        open_time = end - delta * (count - i)  # last candle closes exactly at ``end``
        close = price + Decimal("0.1")
        out.append(RawCandle(
            "fixture", symbol, tf.value, open_time,
            str(price), str(max(price, close) * Decimal("1.01")),
            str(min(price, close) * Decimal("0.99")), str(close), "10",
        ))
        price = close
    return out


class _CountingProvider(FixtureUniverseProvider):
    """Counts snapshot() calls to prove exactly one T0 selection."""

    def __init__(self, markets):
        super().__init__(markets)
        self.snapshots = 0

    def snapshot(self):
        self.snapshots += 1
        return super().snapshot()


def _p9_settings(tmp_path, **over):
    base = dict(
        paper_universe_enabled=True,
        paper_universe_min_quote_volume=Decimal("0"),
        market_symbols=["DOGE/USDT"],  # a DIFFERENT .env universe — must be IGNORED for P9
    )
    base.update(over)
    return paper_settings(tmp_path, **base)


def _warm_adapter(symbols):
    """Fixture market adapter with >=300 warm 1h & 4h candles for each symbol."""
    syms = [s if isinstance(s, Symbol) else Symbol.parse(str(s)) for s in symbols]
    ohlcv = {}
    for s in syms:
        sym = str(s)
        ohlcv[(sym, "1h")] = _candles(sym, Timeframe.H1)
        ohlcv[(sym, "4h")] = _candles(sym, Timeframe.H4)
    return FixtureExchangeAdapter(
        ohlcv=ohlcv, symbols=syms, timeframes=[Timeframe.H1, Timeframe.H4],
    )


UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def _start_new(tmp_path, markets=None, *, provider=None, adapter=None):
    settings = _p9_settings(tmp_path)
    main_sf = main_factory(settings)
    markets = markets or [_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800), _mkt("SOL/USDT", 700)]
    provider = provider or _CountingProvider(markets)
    adapter = adapter if adapter is not None else _warm_adapter([m.symbol for m in markets])
    runner, run_id, uni_hash = start_paper_system(
        settings, main_sf, now=T0, universe_provider=provider, market_adapter=adapter,
        news_adapter=news_adapter(), analyst_provider=FixtureAnalystProvider(APPROVE),
    )
    return settings, main_sf, runner, run_id, uni_hash, provider


# --- A/B/C/D/E/F. one selection → persist == passed symbols, ordered, hashed --------
def test_new_p9_run_single_selection_persist_and_pass(tmp_path) -> None:
    settings, main_sf, runner, run_id, uni_hash, provider = _start_new(tmp_path)
    assert provider.snapshots == 1                                   # A/F: exactly ONE snapshot
    passed = [str(s) for s in runner._cfg.symbols]
    assert passed == UNIVERSE                                        # D: rank order preserved
    persisted, phash = load_frozen_universe(main_sf, run_id)
    assert [str(s) for s in persisted] == UNIVERSE                   # B/C: persisted == passed
    assert phash == uni_hash                                         # E: hash preserved
    # G: the .env MARKET_SYMBOLS (DOGE) was NOT used
    assert "DOGE/USDT" not in passed


# --- G. P9 startup never uses .env MARKET_SYMBOLS ----------------------------------
def test_p9_ignores_env_market_symbols(tmp_path) -> None:
    _s, _m, runner, _rid, _h, _p = _start_new(tmp_path)
    assert [str(s) for s in runner._cfg.symbols] == UNIVERSE  # not ["DOGE/USDT"]


# --- H. fail-closed conditions ------------------------------------------------------
def test_fail_closed_snapshot_failure(tmp_path) -> None:
    class Boom(FixtureUniverseProvider):
        def snapshot(self):
            raise RuntimeError("binance snapshot down")

    settings = _p9_settings(tmp_path)
    main_sf = main_factory(settings)
    with pytest.raises(PaperRunError, match="snapshot failed"):
        start_paper_system(settings, main_sf, now=T0, universe_provider=Boom([]),
                           market_adapter=_warm_adapter([]))


def test_fail_closed_empty_eligible_universe(tmp_path) -> None:
    settings = _p9_settings(tmp_path, paper_universe_min_quote_volume=Decimal("1000000000000"))
    main_sf = main_factory(settings)
    prov = _CountingProvider([_mkt("BTC/USDT", 900)])  # below the huge floor → empty
    with pytest.raises(PaperRunError, match="empty eligible universe"):
        start_paper_system(settings, main_sf, now=T0, universe_provider=prov,
                           market_adapter=_warm_adapter([Symbol.parse("BTC/USDT")]))


def test_fail_closed_empty_after_history_screen(tmp_path) -> None:
    # all candidates fail warmup (empty adapter → 0 candles < 300) → empty after screen
    settings = _p9_settings(tmp_path)
    main_sf = main_factory(settings)
    prov = _CountingProvider([_mkt("BTC/USDT", 900), _mkt("ETH/USDT", 800)])
    with pytest.raises(PaperRunError, match="after T0 history screen"):
        start_paper_system(settings, main_sf, now=T0, universe_provider=prov,
                           market_adapter=FixtureExchangeAdapter(ohlcv={}))  # no history


# --- I. standalone / non-P9 behavior unchanged -------------------------------------
def test_standalone_non_p9_unchanged(tmp_path) -> None:
    settings = paper_settings(tmp_path, market_symbols=["BTC/USDT"])  # universe_enabled=False
    main_sf = main_factory(settings)
    runner, run_id, uni_hash = start_paper_system(
        settings, main_sf, now=T0, market_adapter=FixtureExchangeAdapter(ohlcv={}),
        news_adapter=news_adapter(), analyst_provider=FixtureAnalystProvider(APPROVE),
    )
    assert uni_hash is None                                    # no universe selection
    assert [str(s) for s in runner._cfg.symbols] == ["BTC/USDT"]
    # no paper_universe persisted for a standalone run
    assert load_frozen_universe.__name__  # sanity; standalone has no frozen universe
    with session_scope(runner._sf) as s:
        assert s.scalars(select(PaperUniverseRecord)).first() is None


# --- J/M. resume reuses the frozen universe; no new selection, no mutation ----------
def test_resume_reuses_frozen_universe_no_reselection(tmp_path) -> None:
    settings, main_sf, runner, run_id, uni_hash, _p = _start_new(tmp_path)
    # simulate a CLEAN shutdown: release the OS lock + close the run (clears owner)
    from app.paper.store import close_paper_run, release_run_lock
    release_run_lock(runner._lock)
    close_paper_run(main_sf, run_id, status="stopped")

    resume_provider = _CountingProvider([_mkt("XRP/USDT", 999)])  # a DIFFERENT universe
    runner2, rid2, hash2 = start_paper_system(
        settings, main_sf, now=T0, run_id=run_id, universe_provider=resume_provider,
        market_adapter=_warm_adapter([Symbol.parse(s) for s in UNIVERSE]),
        news_adapter=news_adapter(), analyst_provider=FixtureAnalystProvider(APPROVE),
    )
    assert rid2 == run_id
    assert resume_provider.snapshots == 0                      # J: NO re-selection on resume
    assert [str(s) for s in runner2._cfg.symbols] == UNIVERSE  # same frozen universe
    assert hash2 == uni_hash                                   # hash verified/unchanged
    # M: persisted rows unchanged (still exactly the original universe)
    persisted, _h = load_frozen_universe(main_sf, run_id)
    assert [str(s) for s in persisted] == UNIVERSE


# --- L. run_id resolves the same frozen universe for the news poller ---------------
def test_run_id_resolves_same_universe_for_poller(tmp_path) -> None:
    _s, main_sf, _runner, run_id, uni_hash, _p = _start_new(tmp_path)
    symbols, phash = load_frozen_universe(main_sf, run_id)  # what the poller would load
    assert [str(s) for s in symbols] == UNIVERSE and phash == uni_hash
