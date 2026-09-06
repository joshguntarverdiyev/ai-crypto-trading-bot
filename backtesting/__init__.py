"""backtesting — pure-quant historical backtest engine, metrics, robustness,
walk-forward/OOS, benchmark, reproducibility (Phase 7).

Offline and deterministic. Replays historical OHLCV through the EXACT, unmodified
P2→P3→P4→P6 quant contracts (features → candidate+cost gate → sizing →
RiskManager → deterministic fill → ledger). It writes NO operational tables and
imports NO ``app.ai`` / ``app.news`` / ``app.engine`` runtime — the news/Claude
layer is excluded (Master Plan §8; no fabricated historical AI). No optimizer /
no automated parameter search / no edge claim (plan §7.1).
"""

from __future__ import annotations

from backtesting.config import BacktestConfig, EntryFillRule, HaltPolicy
from backtesting.version import BACKTEST_ENGINE_VERSION

__all__ = [
    "BACKTEST_ENGINE_VERSION",
    "BacktestConfig",
    "EntryFillRule",
    "HaltPolicy",
]
