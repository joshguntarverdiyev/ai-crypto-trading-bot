"""Deterministic universe selection — offline (Phase 9 redesign)."""

from __future__ import annotations

from decimal import Decimal

from app.market_data.models import Symbol
from app.universe.config import UniverseConfig
from app.universe.models import MarketInfo
from app.universe.provider import FixtureUniverseProvider
from app.universe.selection import apply_history_screen, select_universe


def _m(sym, vol, *, active=True, base=None, quote="USDT", lev=False, hist=None) -> MarketInfo:
    s = Symbol.parse(sym)
    return MarketInfo(
        symbol=s, base=base or s.base, quote=quote, active=active,
        quote_volume_24h=Decimal(str(vol)), is_leveraged=lev, history_ok=hist,
    )


def _markets():
    return [
        _m("BTC/USDT", 1_000_000_000),
        _m("ETH/USDT", 500_000_000),
        _m("SOL/USDT", 200_000_000),
        _m("XRP/USDT", 100_000_000),
        _m("DOGE/USDT", 10_000_000),
        _m("LOWVOL/USDT", 1_000),          # below floor
        _m("ETHUP/USDT", 300_000_000, base="ETHUP"),   # leveraged token
        _m("BTCDOWN/USDT", 300_000_000, base="BTCDOWN"),  # leveraged token
        _m("USDC/USDT", 900_000_000, base="USDC"),     # stablecoin base
        _m("DEAD/USDT", 400_000_000, active=False),    # inactive
        _m("ETH/BTC", 400_000_000, quote="BTC"),       # non-USDT quote
    ]


def test_filters_exclude_all_the_right_things() -> None:
    cfg = UniverseConfig(min_quote_volume=Decimal("1000000"), max_symbols=30)
    sel = select_universe(_markets(), cfg)
    syms = [str(s) for s in sel.symbols]
    assert syms == ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"]  # volume DESC
    reasons = dict(sel.excluded)
    assert reasons["LOWVOL/USDT"] == "below_min_volume"
    assert reasons["ETHUP/USDT"] == "leveraged_token"
    assert reasons["BTCDOWN/USDT"] == "leveraged_token"
    assert reasons["USDC/USDT"] == "stablecoin_base"
    assert reasons["DEAD/USDT"] == "inactive"
    assert reasons["ETH/BTC"] == "quote_mismatch"


def test_ranking_is_volume_desc_then_symbol_asc_and_deterministic() -> None:
    ms = [_m("AAA/USDT", 100), _m("BBB/USDT", 100), _m("CCC/USDT", 200)]
    cfg = UniverseConfig(min_quote_volume=Decimal("0"))
    sel = select_universe(ms, cfg)
    assert [str(s) for s in sel.symbols] == ["CCC/USDT", "AAA/USDT", "BBB/USDT"]  # tie → symbol ASC
    # reproducible hash
    assert select_universe(ms, cfg).selection_hash == sel.selection_hash


def test_max_symbols_cap_and_effective_size() -> None:
    ms = [_m(f"C{i:02d}/USDT", 1000 - i) for i in range(50)]
    cfg = UniverseConfig(min_quote_volume=Decimal("0"), max_symbols=30)
    sel = select_universe(ms, cfg)
    assert sel.size == 30
    assert ("C30/USDT", "rank_over_cap") in sel.excluded


def test_history_screen_drops_without_replacement_and_rehashes() -> None:
    cfg = UniverseConfig(min_quote_volume=Decimal("0"), max_symbols=3)
    ms = [_m("AAA/USDT", 300), _m("BBB/USDT", 200), _m("CCC/USDT", 100), _m("DDD/USDT", 50)]
    sel = select_universe(ms, cfg)  # AAA,BBB,CCC (DDD over cap)
    screened = apply_history_screen(sel, {"BBB/USDT": False})  # BBB fails warmup
    assert [str(s) for s in screened.symbols] == ["AAA/USDT", "CCC/USDT"]  # no promotion of DDD
    assert screened.selection_hash != sel.selection_hash
    assert ("BBB/USDT", "insufficient_history") in screened.excluded


def test_require_history_excludes_known_false_at_snapshot() -> None:
    cfg = UniverseConfig(min_quote_volume=Decimal("0"))
    ms = [_m("AAA/USDT", 100, hist=False), _m("BBB/USDT", 90, hist=True)]
    sel = select_universe(ms, cfg)
    assert [str(s) for s in sel.symbols] == ["BBB/USDT"]
    assert ("AAA/USDT", "insufficient_history") in sel.excluded


def test_fixture_provider_roundtrip() -> None:
    prov = FixtureUniverseProvider(_markets())
    assert len(prov.snapshot()) == len(_markets())


def test_effective_universe_is_min_of_cap_and_survivors() -> None:
    cfg = UniverseConfig(min_quote_volume=Decimal("1000000"), max_symbols=30)
    sel = select_universe(_markets(), cfg)
    assert sel.size == 5  # only 5 survive filters though N_max=30
