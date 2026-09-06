"""Backtest configuration + version tag (Phase 7 — source of truth).

Deterministic, offline research tooling. All values are provisional/illustrative
and **NOT calibrated** — Phase 7 builds the measurement machinery and makes no
edge/performance claim (see the Phase 7 plan §7.1). There is NO optimizer and NO
automated parameter search.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.costs.config import CostScenario
from backtesting.version import BACKTEST_ENGINE_VERSION


class EntryFillRule(StrEnum):
    """How the entry execution reference price is chosen (Phase 7 plan §10).

    In BOTH modes the candidate decision, sizing quantity, and risk evaluation use
    ONLY data known at decision_time; the mode changes only the execution
    reference handed to the (unmodified) PaperBroker.
    """

    NEXT_OPEN = "next_open"  # DEFAULT: reference = bar i+1 open (first executable price)
    SIGNAL_CLOSE = "signal_close"  # reference = bar i close (candidate.entry_ref)


class HaltPolicy(StrEnum):
    """What a HALT-class RiskManager outcome does in a research replay (§14)."""

    END_RUN = "end_run"  # DEFAULT: matches production manual-reset — stop the run
    RESET_NEXT_PERIOD = "reset_next_period"  # research-only: resume next UTC period


@dataclass(frozen=True)
class BacktestConfig:
    """Deterministic backtest parameters. Invariants fail closed at load."""

    dataset_name: str = "example"
    starting_equity: Decimal = Decimal("10000")
    cost_scenario: CostScenario = CostScenario.CONSERVATIVE
    seed: int = 12345
    halt_policy: HaltPolicy = HaltPolicy.END_RUN
    entry_fill_rule: EntryFillRule = EntryFillRule.NEXT_OPEN
    min_operational_trades: int = 100
    artifacts_dir: str = "data/backtests"

    def __post_init__(self) -> None:
        if not self.dataset_name:
            raise ValueError("dataset_name must be non-empty")
        if self.starting_equity <= 0:
            raise ValueError("starting_equity must be > 0")
        if self.min_operational_trades < 1:
            raise ValueError("min_operational_trades must be >= 1")
        if not self.artifacts_dir:
            raise ValueError("artifacts_dir must be non-empty")

    @property
    def version_tag(self) -> str:
        return (
            f"{BACKTEST_ENGINE_VERSION}|ds{self.dataset_name}"
            f"|eq{self.starting_equity}|sc{self.cost_scenario.value}"
            f"|seed{self.seed}|halt{self.halt_policy.value}"
            f"|fill{self.entry_fill_rule.value}|minT{self.min_operational_trades}"
        )
