"""Deterministic Claude call budget (Phase 9 redesign — cost control at scale).

Expanding from 2 to ~30 symbols means Claude could be consulted for many candidates
per boundary. ``BudgetedAnalyst`` is a drop-in **subclass** of the frozen
``ClaudeAnalyst`` (so the engine's ``analyst: ClaudeAnalyst`` contract is unchanged;
NOT a second analyst) that caps ACTUAL provider calls per boundary and per run
WITHOUT weakening any strategy/risk gate and WITHOUT letting Claude make risk
decisions: when the budget is exhausted the candidate gets a fail-closed
``HOLD (UNAVAILABLE)`` — no provider call, no Claude-less entry.

Budget is consumed only when the analyst would ACTUALLY call the provider (enabled
AND news AVAILABLE), so news-unavailable no-ops never waste budget. Per-boundary
counts reset on a new ``decision_time``; the per-run count is seeded from durable
funnel counters for restart-safety. The runner already short-circuits
already-processed ``(decision_time, symbol)`` before ``process_tick``, so restart
never duplicates a call; this only bounds cost.
"""

from __future__ import annotations

from datetime import datetime

from app.ai.analyst import ClaudeAnalyst
from app.ai.config import AIConfig
from app.ai.models import AnalystAction, AnalystFailure, AnalystVerdict
from app.ai.provider import AnalystProvider
from app.news.models import NewsAvailability, NewsContext
from app.strategy.models import Candidate


class BudgetedAnalyst(ClaudeAnalyst):
    """Budget-aware ``ClaudeAnalyst`` (same config/provider; budgeted ``analyze``)."""

    def __init__(
        self,
        config: AIConfig,
        provider: AnalystProvider | None,
        *,
        max_per_boundary: int,
        max_per_run: int,
        run_calls_seed: int = 0,
    ) -> None:
        super().__init__(config, provider)
        if max_per_boundary < 1 or max_per_run < 1:
            raise ValueError("Claude budgets must be >= 1")
        self._max_boundary = max_per_boundary
        self._max_run = max_per_run
        self._run_calls = max(0, run_calls_seed)
        self._boundary_time: datetime | None = None
        self._boundary_calls = 0
        # Per-boundary observable counters (reset each boundary).
        self.calls = 0
        self.budget_skipped = 0

    def reset_boundary(self, decision_time: datetime) -> None:
        self._boundary_time = decision_time
        self._boundary_calls = 0
        self.calls = 0
        self.budget_skipped = 0

    def _new_boundary(self, decision_time: datetime) -> None:
        if self._boundary_time != decision_time:
            self.reset_boundary(decision_time)

    def _would_call_provider(self, news: NewsContext) -> bool:
        """True iff the analyst would actually invoke the provider (i.e. incur cost)."""
        return bool(
            self._cfg.analyst_enabled
            and self._provider is not None
            and news.availability is NewsAvailability.AVAILABLE
        )

    @property
    def run_calls(self) -> int:
        return self._run_calls

    def analyze(
        self, candidate: Candidate, news: NewsContext, *, decision_time: datetime
    ) -> AnalystVerdict:
        self._new_boundary(decision_time)
        if self._would_call_provider(news):
            if self._boundary_calls >= self._max_boundary or self._run_calls >= self._max_run:
                self.budget_skipped += 1
                # Fail-closed: no provider call, no entry (HOLD). UNAVAILABLE reuses the
                # frozen enum (no schema change); the boundary funnel records the
                # distinct ``claude_budget_skipped`` count for audit.
                return self._verdict(
                    decision=None, action=AnalystAction.HOLD,
                    failure=AnalystFailure.UNAVAILABLE, decision_time=decision_time,
                    started=0.0, news=news,
                )
            self._boundary_calls += 1
            self._run_calls += 1
            self.calls += 1
        return super().analyze(candidate, news, decision_time=decision_time)
