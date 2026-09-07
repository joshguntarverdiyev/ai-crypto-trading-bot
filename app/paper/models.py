"""Phase 9 in-process result types.

The P9 runner drives the frozen P6 ``TradingEngine`` and records ONE
``paper_decisions`` row per processed boundary/symbol. ``PaperOutcome`` mirrors the
engine's ``TickOutcome`` values (so a ``TickResult.outcome.value`` is a valid
``PaperOutcome``) plus a runner-level ``DATA_FAILURE`` (a gap, not a decision).
"""

from __future__ import annotations

from enum import StrEnum


class PaperOutcome(StrEnum):
    TRADE = "trade"  # entry executed into the evolving paper book
    EXIT = "exit"  # stop/target exit executed
    HOLD = "hold"  # pipeline ran; fail-closed no-trade (a real decision)
    REJECT = "reject"  # RiskManager REJECT (a real decision)
    KILL_PAUSED = "kill_paused"  # PAUSED: no new entries (protective exits still run)
    KILL_HALTED = "kill_halted"  # HALTED with no open position to protect
    ERROR = "error"  # unrecoverable (→ HALT)
    DATA_FAILURE = "data_failure"  # runner-level adapter/infra failure — a GAP, not a decision


# Runner-level outcomes that are gaps, not durable per-boundary decisions.
GAP_OUTCOMES = frozenset({PaperOutcome.DATA_FAILURE})
