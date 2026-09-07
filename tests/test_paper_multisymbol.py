"""P9 multi-symbol same-boundary: canonical order + sequential committed visibility."""

from __future__ import annotations

import inspect

from app.ai.fixture_provider import FixtureAnalystProvider
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.models import Symbol
from app.paper.build import build_paper_system
from tests._p6_helpers import build_1h_raw, decision_now
from tests._p9_helpers import APPROVE, main_factory, news_adapter, paper_settings


def _both_symbol_adapter() -> FixtureExchangeAdapter:
    return FixtureExchangeAdapter(
        ohlcv={
            ("BTC/USDT", "1h"): build_1h_raw("BTC/USDT"),
            ("BTC/USDT", "4h"): [],
            ("ETH/USDT", "1h"): build_1h_raw("ETH/USDT"),
            ("ETH/USDT", "4h"): [],
        },
    )


def _build(tmp_path):
    # max ONE simultaneous position at the RISK layer so the second canonical symbol
    # is REJECTED only if it sees the first symbol's already-committed position.
    settings = paper_settings(
        tmp_path,
        market_symbols=["BTC/USDT", "ETH/USDT"],
        risk_max_simultaneous_positions=1,
        sizing_max_simultaneous_positions=2,  # sizing allows; risk is the authority
    )
    main_sf = main_factory(settings)
    runner, run_id = build_paper_system(
        settings, main_sf, market_adapter=_both_symbol_adapter(),
        news_adapter=news_adapter(), analyst_provider=FixtureAnalystProvider(APPROVE),
    )
    return runner, run_id, settings


def test_second_symbol_sees_first_same_boundary_fill(tmp_path) -> None:
    runner, run_id, settings = _build(tmp_path)
    # 1) deterministic canonical order (BTC before ETH)
    assert runner._cfg.canonical_symbols == (Symbol.parse("BTC/USDT"), Symbol.parse("ETH/USDT"))

    out = runner.run_once(decision_now())
    assert [str(r.symbol) for r in out] == ["BTC/USDT", "ETH/USDT"]
    # 2) first symbol commits an entry
    assert out[0].outcome.value == "trade"
    # 3)+4) the second symbol's RiskManager saw the first symbol's committed position
    #        (open_count == 1 ⇒ max-simultaneous-positions REJECT this same boundary)
    assert out[1].outcome.value == "reject"
    assert "position" in out[1].reason  # e.g. "max_positions"


def test_no_provisional_reservation_machinery() -> None:
    # 5) P9 relies on sequential committed state, NOT the P7 backtest 'provisional'
    #    reservation loop. Assert the runner carries no such machinery.
    import app.paper.runner as runner_mod

    assert "provisional" not in inspect.getsource(runner_mod).lower()


def test_multisymbol_replay_is_deterministic(tmp_path) -> None:
    # 6) identical inputs → identical per-symbol outcomes
    r1, _id1, _s1 = _build(tmp_path / "a")
    r2, _id2, _s2 = _build(tmp_path / "b")
    o1 = [(str(r.symbol), r.outcome.value, r.reason) for r in r1.run_once(decision_now())]
    o2 = [(str(r.symbol), r.outcome.value, r.reason) for r in r2.run_once(decision_now())]
    assert o1 == o2
