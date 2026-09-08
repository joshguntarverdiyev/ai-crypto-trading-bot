"""P9 T0 universe → paper-system market_symbols → news config wiring (offline)."""

from __future__ import annotations

from app.ai.fixture_provider import FixtureAnalystProvider
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.models import Symbol
from app.paper.build import _effective_settings, build_paper_system
from tests._p9_helpers import APPROVE, main_factory, news_adapter, paper_settings

UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "PEPE/USDT"]
BASES = ("BTC", "ETH", "SOL", "XRP", "PEPE")


def _adapter():
    return FixtureExchangeAdapter(ohlcv={})  # construction only; no fetch


def _build(tmp_path, *, universe_symbols=None, market_symbols=None):
    settings = paper_settings(
        tmp_path, **({"market_symbols": market_symbols} if market_symbols else {})
    )
    main_sf = main_factory(settings)
    runner, run_id = build_paper_system(
        settings, main_sf, market_adapter=_adapter(),
        news_adapter=news_adapter(), analyst_provider=FixtureAnalystProvider(APPROVE),
        universe_symbols=universe_symbols,
    )
    return runner, settings


# --- A/B/C. universe propagates to tickers (base assets) + known_assets ------------
def test_universe_propagates_to_news_ticker_config() -> None:
    from app.config import load_settings

    settings = load_settings(_env_file=None)
    uni = [Symbol.parse(s) for s in UNIVERSE]
    eff = _effective_settings(settings, uni)
    # B. tickers are BASE assets (no /USDT), from the universe
    assert eff.crypto_news_config().tickers == BASES
    # C. known_assets populated by the same universe
    assert set(BASES) <= set(eff.news_config().known_assets)


def test_build_paper_system_uses_universe_as_market_symbols(tmp_path) -> None:
    runner, _settings = _build(tmp_path, universe_symbols=[Symbol.parse(s) for s in UNIVERSE])
    # A. the paper system now processes the universe symbols
    assert [str(s) for s in runner._cfg.symbols] == UNIVERSE
    assert [str(s) for s in runner._cfg.processing_order] == UNIVERSE  # universe order preserved


# --- D. one global request; NO per-symbol design ----------------------------------
def test_single_global_comma_separated_request_no_per_symbol() -> None:
    from app.config import load_settings

    eff = _effective_settings(load_settings(_env_file=None), [Symbol.parse(s) for s in UNIVERSE])
    cfg = eff.crypto_news_config()
    assert cfg.max_pages == 1  # bounded pagination
    assert isinstance(cfg.tickers, tuple) and len(cfg.tickers) == 5  # one tuple → one request
    # the adapter joins ALL tickers into ONE request's params (no per-symbol loop)
    joined = ",".join(cfg.tickers)
    assert joined == "BTC,ETH,SOL,XRP,PEPE"


# --- E. explicit BTC/ETH configuration remains backward compatible ----------------
def test_explicit_btc_eth_unchanged_when_no_universe(tmp_path) -> None:
    runner, _settings = _build(tmp_path, universe_symbols=None,
                               market_symbols=["BTC/USDT", "ETH/USDT"])
    assert [str(s) for s in runner._cfg.symbols] == ["BTC/USDT", "ETH/USDT"]

    from app.config import load_settings
    s = load_settings(_env_file=None)  # default market_symbols = BTC/ETH
    assert _effective_settings(s, None) is s  # unchanged object
    assert s.crypto_news_config().tickers == ("BTC", "ETH")
    assert s.news_config().known_assets == ("BTC", "ETH")


# --- F. the frozen universe / base settings are not mutated -----------------------
def test_effective_settings_does_not_mutate_inputs() -> None:
    from app.config import load_settings

    s = load_settings(_env_file=None)
    uni = [Symbol.parse(x) for x in UNIVERSE]
    before_market = list(s.market_symbols)
    before_uni = list(uni)
    _effective_settings(s, uni)
    assert list(s.market_symbols) == before_market  # base settings unchanged
    assert uni == before_uni  # the frozen universe list is not mutated


# --- G. no strategy/risk/sizing/execution/validation behavior change --------------
def test_wiring_does_not_change_risk_or_validation_limits() -> None:
    from app.config import load_settings

    s = load_settings(_env_file=None)
    eff = _effective_settings(s, [Symbol.parse(x) for x in UNIVERSE])
    # risk / sizing / validation limits are identical (only market_symbols changed)
    assert eff.risk_config() == s.risk_config()
    assert eff.sizing_config() == s.sizing_config()
    assert eff.strategy_config() == s.strategy_config()
    assert eff.cost_config() == s.cost_config()
    c0, c1 = s.paper_validation_config(), eff.paper_validation_config()
    assert (c1.validation_days, c1.universe_max_symbols, c1.mc_max_drawdown_ceiling,
            c1.min_meaningful_trades, c1.claude_max_per_boundary) == (
        c0.validation_days, c0.universe_max_symbols, c0.mc_max_drawdown_ceiling,
        c0.min_meaningful_trades, c0.claude_max_per_boundary)
