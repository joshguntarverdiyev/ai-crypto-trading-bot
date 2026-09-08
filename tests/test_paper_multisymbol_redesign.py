"""P9 redesign multi-symbol: priority order + runner-level Claude budget (offline)."""

from __future__ import annotations

from sqlalchemy import select

from app.ai.fixture_provider import FixtureAnalystProvider
from app.database import session_scope
from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.models import Symbol
from app.models import PaperBoundaryFunnelRecord
from app.paper.build import build_paper_system
from app.paper.config import PaperValidationConfig
from tests._p6_helpers import build_1h_raw, decision_now
from tests._p9_helpers import APPROVE, main_factory, news_adapter, paper_settings


def test_processing_order_preserves_universe_rank_when_enabled() -> None:
    syms = (Symbol.parse("ETH/USDT"), Symbol.parse("BTC/USDT"))  # ETH first (rank order)
    off = PaperValidationConfig(symbols=syms, universe_enabled=False)
    on = PaperValidationConfig(symbols=syms, universe_enabled=True)
    # legacy: canonical sorted (BTC, ETH); redesign: preserve given rank order (ETH, BTC)
    assert [str(s) for s in off.processing_order] == ["BTC/USDT", "ETH/USDT"]
    assert [str(s) for s in on.processing_order] == ["ETH/USDT", "BTC/USDT"]


def _both_symbol_adapter() -> FixtureExchangeAdapter:
    return FixtureExchangeAdapter(
        ohlcv={
            ("BTC/USDT", "1h"): build_1h_raw("BTC/USDT"), ("BTC/USDT", "4h"): [],
            ("ETH/USDT", "1h"): build_1h_raw("ETH/USDT"), ("ETH/USDT", "4h"): [],
        },
    )


def test_runner_claude_budget_skips_second_candidate(tmp_path) -> None:
    # Per-boundary Claude budget = 1: with two candidate symbols, only ONE provider
    # call happens; the second is budget-skipped → HOLD (no Claude-less entry).
    settings = paper_settings(
        tmp_path, market_symbols=["BTC/USDT", "ETH/USDT"],
        paper_claude_max_per_boundary=1, paper_claude_max_per_run=1000,
    )
    main_sf = main_factory(settings)
    runner, run_id = build_paper_system(
        settings, main_sf, market_adapter=_both_symbol_adapter(),
        news_adapter=news_adapter(), analyst_provider=FixtureAnalystProvider(APPROVE),
    )
    out = runner.run_once(decision_now())
    outcomes = {str(r.symbol): (r.outcome.value, r.stage) for r in out}
    # BTC (canonical first) trades; ETH is budget-skipped at the analyst stage → HOLD
    assert outcomes["BTC/USDT"][0] == "trade"
    assert outcomes["ETH/USDT"] == ("hold", "analyst")

    with session_scope(runner._sf) as s:
        f = s.scalars(select(PaperBoundaryFunnelRecord)).first()
        assert f.claude_calls == 1 and f.claude_budget_skipped == 1
        assert f.universe_size == 2 and f.entries == 1


def test_runner_budget_seed_restart_safe(tmp_path) -> None:
    # After a boundary consumes the per-run budget, a fresh build (restart) seeds the
    # run count from the durable funnel and continues to fail closed.
    settings = paper_settings(
        tmp_path, market_symbols=["BTC/USDT", "ETH/USDT"],
        paper_claude_max_per_boundary=5, paper_claude_max_per_run=1,
    )
    main_sf = main_factory(settings)
    runner, run_id = build_paper_system(
        settings, main_sf, market_adapter=_both_symbol_adapter(),
        news_adapter=news_adapter(), analyst_provider=FixtureAnalystProvider(APPROVE),
    )
    runner.run_once(decision_now())  # consumes 1 run-call (the per-run cap)
    # simulate a clean restart: release the OS single-writer lock the first runner holds
    from app.paper.store import release_run_lock
    release_run_lock(runner._lock)
    # rebuild the SAME run → seed from funnel (=1) → budget already exhausted
    runner2, _ = build_paper_system(
        settings, main_sf, run_id=run_id, market_adapter=_both_symbol_adapter(),
        news_adapter=news_adapter(), analyst_provider=FixtureAnalystProvider(APPROVE),
    )
    assert runner2._budget.run_calls >= 1  # seeded from durable funnel counters
