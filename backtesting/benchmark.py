"""Buy-and-hold benchmark (Phase 7) — CONTEXT ONLY (Master Plan §0.1-5 / §G).

Buy-and-hold is reported alongside the strategy as risk-adjusted CONTEXT, never as
a single "must beat" gate: a strategy that underperforms B&H at far lower drawdown
may still be worth paper validation, and one that beats B&H with intolerable
drawdown is NOT a success. Assumptions are explicit: buy at the first close (entry
fee once), mark-to-market each bar, exit fee once at the final close.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.costs.config import CostConfig, CostScenario
from app.market_data.models import Symbol, Timeframe
from backtesting.costs import scenario_market_costs
from backtesting.dataset import Dataset


@dataclass(frozen=True)
class BenchmarkResult:
    symbol: str
    starting_equity: float
    ending_equity: float
    total_return: float
    max_drawdown: float
    entry_fee: float
    exit_fee: float
    note: str = (
        "Buy-and-hold is CONTEXT only, not a single 'must beat' gate (Master Plan §0.1-5)."
    )


def _max_drawdown(equity: list[float]) -> float:
    peak = None
    max_dd = 0.0
    for eq in equity:
        if peak is None or eq > peak:
            peak = eq
        elif peak and peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    return max_dd


def buy_and_hold(
    dataset: Dataset,
    symbol: Symbol,
    *,
    starting_equity: Decimal,
    cost_config: CostConfig,
    scenario: CostScenario = CostScenario.CONSERVATIVE,
    timeframe: Timeframe = Timeframe.H1,
) -> BenchmarkResult | None:
    """Compute a single-asset buy-and-hold equity path under stated cost assumptions."""
    candles = dataset.candles(symbol, timeframe)
    if len(candles) < 2:
        return None
    spread_pct, slippage_pct = scenario_market_costs(cost_config, scenario)
    taker = float(cost_config.taker_fee_pct)
    start = float(starting_equity)

    # Buy at the first close with adverse half-spread + slippage; one taker fee.
    entry_ref = float(candles[0].close)
    entry_price = entry_ref * (1.0 + spread_pct / 2 + slippage_pct)
    entry_fee = start * taker
    invest = start - entry_fee
    qty = invest / entry_price if entry_price > 0 else 0.0

    # Mark-to-market equity path. Leftover cash after buying is
    # start - entry_fee - qty*entry_price ~= 0; hold qty across the series.
    cash_leftover = start - entry_fee - qty * entry_price
    equity_path = [start] + [cash_leftover + qty * float(c.close) for c in candles[1:]]

    # Exit fee applied once at the final close (to compare like-for-like net).
    exit_ref = float(candles[-1].close)
    exit_price = exit_ref * (1.0 - spread_pct / 2 - slippage_pct)
    proceeds = qty * exit_price
    exit_fee = proceeds * taker
    ending = cash_leftover + proceeds - exit_fee
    equity_path[-1] = ending

    total_return = (ending / start - 1.0) if start > 0 else 0.0
    return BenchmarkResult(
        symbol=str(symbol), starting_equity=start, ending_equity=ending,
        total_return=total_return, max_drawdown=_max_drawdown(equity_path),
        entry_fee=entry_fee, exit_fee=exit_fee,
    )
