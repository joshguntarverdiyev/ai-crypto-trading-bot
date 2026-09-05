"""Shared builders for Phase 5 tests (candidate, news context, analyst responses)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.costs.manager import CostManager
from app.market_data.models import Symbol, Timeframe
from app.news.config import NewsConfig
from app.news.fixture_adapter import FixtureNewsAdapter
from app.news.models import NewsContext, NewsItemRaw
from app.news.service import NewsService
from app.strategy.models import Candidate, SignalDirection

BTC = Symbol.parse("BTC/USDT")
DT = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
_EA = CostManager().assess_edge(expected_gross_move_pct=0.06, atr_pct=0.02)


def candidate(symbol: Symbol = BTC) -> Candidate:
    return Candidate(
        direction=SignalDirection.LONG, source="fixture", symbol=symbol,
        timeframe=Timeframe.H1, open_time=DT - Timeframe.H1.delta, close_time=DT,
        entry_ref=100.0, stop_price=97.0, target_price=106.0, risk_distance_pct=0.03,
        expected_gross_move_pct=0.06, reward_risk=2.0, atr=2.0, atr_pct=0.02,
        confirmed_4h=True, governing_4h_open_time=None, edge_assessment=_EA,
        strategy_version="strat-v1", config_version="x",
    )


def available_news() -> NewsContext:
    avail = DT - timedelta(hours=1)
    raw = NewsItemRaw(
        source="fixture", source_id="n1", title="BTC update",
        published_at=avail, available_at=avail, assets=("BTC",),
    )
    return NewsService(FixtureNewsAdapter([raw]), NewsConfig()).build_context(
        decision_time=DT, now=DT
    )


def empty_news() -> NewsContext:
    return NewsService(FixtureNewsAdapter([]), NewsConfig()).build_context(
        decision_time=DT, now=DT
    )


def response(
    decision: str = "approve",
    *,
    confidence: float = 0.9,
    reason_codes: list[str] | None = None,
    affected_assets: list[str] | None = None,
    event_risk: str = "low",
    evidence: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "decision": decision,
            "confidence": confidence,
            "reason_codes": reason_codes if reason_codes is not None else [],
            "affected_assets": affected_assets if affected_assets is not None else ["BTC"],
            "event_risk": event_risk,
            "evidence": evidence if evidence is not None else ["e1"],
        }
    )
