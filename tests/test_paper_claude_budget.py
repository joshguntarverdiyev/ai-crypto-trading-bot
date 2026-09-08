"""Deterministic Claude budget (Phase 9 redesign) — offline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.ai.config import AIConfig
from app.ai.fixture_provider import FixtureAnalystProvider
from app.ai.models import AnalystAction, AnalystFailure
from app.paper.budget import BudgetedAnalyst
from tests._p5_helpers import available_news, candidate, empty_news, response


class CountingProvider(FixtureAnalystProvider):
    """Wraps the fixture provider to count actual provider invocations."""

    def __init__(self, payload: str) -> None:
        super().__init__(payload)
        self.calls = 0

    def analyze(self, request):  # noqa: ANN001, ANN201
        self.calls += 1
        return super().analyze(request)


DT = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


def _budget(*, payload=None, max_per_boundary=2, max_per_run=100, run_calls_seed=0):
    provider = CountingProvider(payload or response("approve"))
    b = BudgetedAnalyst(
        AIConfig(analyst_enabled=True), provider,
        max_per_boundary=max_per_boundary, max_per_run=max_per_run,
        run_calls_seed=run_calls_seed,
    )
    return b, provider


def test_per_boundary_cap_blocks_extra_candidates_without_provider_call() -> None:
    b, provider = _budget(max_per_boundary=2, max_per_run=100)
    news = available_news()
    v1 = b.analyze(candidate(), news, decision_time=DT)
    v2 = b.analyze(candidate(), news, decision_time=DT)
    v3 = b.analyze(candidate(), news, decision_time=DT)  # over per-boundary cap
    assert v1.action is AnalystAction.PROCEED and v2.action is AnalystAction.PROCEED
    assert v3.action is AnalystAction.HOLD and v3.failure is AnalystFailure.UNAVAILABLE
    assert provider.calls == 2  # the 3rd never hit the provider
    assert b.calls == 2 and b.budget_skipped == 1


def test_boundary_counter_resets_next_boundary() -> None:
    b, provider = _budget(max_per_boundary=1, max_per_run=100)
    news = available_news()
    b.analyze(candidate(), news, decision_time=DT)
    over = b.analyze(candidate(), news, decision_time=DT)
    assert over.action is AnalystAction.HOLD
    # next boundary → budget refreshed
    nxt = b.analyze(candidate(), news, decision_time=DT + timedelta(hours=1))
    assert nxt.action is AnalystAction.PROCEED
    assert provider.calls == 2


def test_per_run_cap_persists_across_boundaries() -> None:
    b, provider = _budget(max_per_boundary=10, max_per_run=2)
    news = available_news()
    b.analyze(candidate(), news, decision_time=DT)
    b.analyze(candidate(), news, decision_time=DT + timedelta(hours=1))
    over = b.analyze(candidate(), news, decision_time=DT + timedelta(hours=2))  # run cap hit
    assert over.action is AnalystAction.HOLD and provider.calls == 2
    assert b.run_calls == 2


def test_news_unavailable_does_not_consume_budget() -> None:
    b, provider = _budget(max_per_boundary=1, max_per_run=100)
    # news UNAVAILABLE → inner returns HOLD without a provider call; budget untouched
    v = b.analyze(candidate(), empty_news(), decision_time=DT)
    assert v.action is AnalystAction.HOLD and provider.calls == 0
    assert b.calls == 0 and b.budget_skipped == 0
    # a subsequent AVAILABLE candidate still has its budget
    v2 = b.analyze(candidate(), available_news(), decision_time=DT)
    assert v2.action is AnalystAction.PROCEED and provider.calls == 1


def test_run_seed_restart_safe() -> None:
    b, provider = _budget(max_per_boundary=10, max_per_run=3, run_calls_seed=3)
    over = b.analyze(candidate(), available_news(), decision_time=DT)  # already at seed
    assert over.action is AnalystAction.HOLD and provider.calls == 0
