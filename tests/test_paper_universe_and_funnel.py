"""P9 redesign: funnel-counter persistence + universe build/persist (offline)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.database import session_scope
from app.market_data.models import Symbol
from app.models import PaperBoundaryFunnelRecord, PaperUniverseRecord
from app.paper.universe_build import build_and_persist_universe
from app.universe.models import MarketInfo
from app.universe.provider import FixtureUniverseProvider
from tests._p6_helpers import decision_now
from tests._p9_helpers import APPROVE, build_paper, main_factory, paper_settings


def test_funnel_row_persisted_per_boundary(tmp_path) -> None:
    runner, run_id, _main_sf, _settings = build_paper(tmp_path, analyst_response=APPROVE)
    runner.run_once(decision_now())
    with session_scope(runner._sf) as s:
        rows = s.scalars(select(PaperBoundaryFunnelRecord)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.paper_run_id == run_id
        assert row.universe_size >= 1
        # entries/candidates are consistent non-negative counters
        assert row.entries >= 0 and row.candidates >= 0 and row.claude_calls >= 0


def test_funnel_is_idempotent_on_reprocess(tmp_path) -> None:
    runner, _run_id, _main_sf, _settings = build_paper(tmp_path, analyst_response=APPROVE)
    now = decision_now()
    runner.run_once(now)
    runner.run_once(now)  # same boundary again → idempotent (no second funnel row)
    with session_scope(runner._sf) as s:
        rows = s.scalars(select(PaperBoundaryFunnelRecord)).all()
        assert len(rows) == 1


def _mkt(sym, vol, base=None):
    s = Symbol.parse(sym)
    return MarketInfo(symbol=s, base=base or s.base, quote="USDT", active=True,
                      quote_volume_24h=Decimal(str(vol)))


def test_universe_build_and_persist_with_history_screen(tmp_path) -> None:
    settings = paper_settings(tmp_path, paper_universe_enabled=True,
                              paper_universe_min_quote_volume=Decimal("1000000"))
    main_sf = main_factory(settings)  # noqa: F841 (creates main db)
    # build a run DB via a normal paper build to get a run_sf
    runner, run_id, _msf, _s = build_paper(tmp_path, settings=settings, main_sf=main_sf)
    cfg = settings.paper_validation_config()
    provider = FixtureUniverseProvider([
        _mkt("BTC/USDT", 1_000_000_000),
        _mkt("ETH/USDT", 500_000_000),
        _mkt("SOL/USDT", 200_000_000),
        _mkt("LOWVOL/USDT", 1000),  # excluded by floor
    ])
    sel = build_and_persist_universe(
        runner._sf, run_id, provider=provider, cfg=cfg,
        now=datetime(2026, 9, 8, tzinfo=UTC),
        history_ok={"SOL/USDT": False},  # SOL fails warmup → dropped, no replacement
    )
    assert [str(s) for s in sel.symbols] == ["BTC/USDT", "ETH/USDT"]
    with session_scope(runner._sf) as s:
        rows = s.scalars(
            select(PaperUniverseRecord).order_by(PaperUniverseRecord.rank)
        ).all()
        assert [r.symbol for r in rows] == ["BTC/USDT", "ETH/USDT"]
        assert all(r.selection_hash == sel.selection_hash for r in rows)
