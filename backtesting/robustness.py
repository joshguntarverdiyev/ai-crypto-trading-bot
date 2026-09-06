"""Robustness analysis (Phase 7) — pure-Python, seeded, deterministic.

Parameter perturbation (ENUMERATED — never an optimizer, plan §7.1/§18),
trade-removal sensitivity, seeded Monte Carlo (trade-order reshuffle for the
drawdown distribution; resample for the expectancy distribution), and
time/regime/cost-scenario segmentation (Master Plan §10).

Interpretation guardrails accompany each output in the report: Monte Carlo
reshuffle ASSUMES trade independence — cross-check the §-statistics
autocorrelation result before trusting a drawdown distribution.

There is deliberately NO grid/random/Bayesian search and NO "select the best
parameters" routine — these functions only *report* across a caller-supplied,
fixed set of perturbations.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

from app.costs.config import CostConfig, CostScenario
from app.execution.config import PaperConfig
from app.indicators.config import IndicatorConfig
from app.market_data.models import Symbol
from app.risk.config import RiskConfig
from app.sizing.config import SizingConfig
from app.strategy.config import StrategyConfig
from backtesting.config import BacktestConfig
from backtesting.dataset import Dataset
from backtesting.metrics import Metrics, compute_metrics
from backtesting.models import BacktestResult, BacktestTrade
from backtesting.statistics import _percentile


@dataclass(frozen=True)
class MonteCarloDrawdown:
    seed: int
    iterations: int
    p50: float
    p95: float
    p99: float
    worst: float


@dataclass(frozen=True)
class MonteCarloExpectancy:
    seed: int
    iterations: int
    p05: float
    p50: float
    p95: float
    fraction_positive: float


@dataclass(frozen=True)
class Segment:
    label: str
    trade_count: int
    net_expectancy: float | None
    net_pnl: float


def _max_dd_from_pnls(starting_equity: float, ordered: list[float]) -> float:
    eq = starting_equity
    peak = starting_equity
    max_dd = 0.0
    for pnl in ordered:
        eq += pnl
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    return max_dd


def monte_carlo_max_drawdown(
    net_pnls: list[float] | list[Decimal],
    starting_equity: float | Decimal,
    *,
    seed: int,
    iterations: int = 2000,
) -> MonteCarloDrawdown | None:
    xs = [float(v) for v in net_pnls]
    if len(xs) < 2:
        return None
    start = float(starting_equity)
    rng = random.Random(seed)
    dds: list[float] = []
    for _ in range(iterations):
        order = xs[:]
        rng.shuffle(order)
        dds.append(_max_dd_from_pnls(start, order))
    dds.sort()
    return MonteCarloDrawdown(
        seed=seed, iterations=iterations,
        p50=_percentile(dds, 0.50), p95=_percentile(dds, 0.95),
        p99=_percentile(dds, 0.99), worst=dds[-1],
    )


def monte_carlo_expectancy(
    net_pnls: list[float] | list[Decimal], *, seed: int, iterations: int = 2000
) -> MonteCarloExpectancy | None:
    xs = [float(v) for v in net_pnls]
    n = len(xs)
    if n < 2:
        return None
    rng = random.Random(seed)
    means: list[float] = []
    positive = 0
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += xs[rng.randrange(n)]
        m = total / n
        means.append(m)
        if m > 0:
            positive += 1
    means.sort()
    return MonteCarloExpectancy(
        seed=seed, iterations=iterations,
        p05=_percentile(means, 0.05), p50=_percentile(means, 0.50),
        p95=_percentile(means, 0.95), fraction_positive=positive / iterations,
    )


def trade_removal_curve(
    net_pnls: list[float] | list[Decimal], *, up_to: int = 5
) -> list[tuple[int, float | None]]:
    """Expectancy after removing the best k trades, k = 0..up_to (§10 outlier dep)."""
    xs = sorted((float(v) for v in net_pnls), reverse=True)  # best first
    out: list[tuple[int, float | None]] = []
    n = len(xs)
    for k in range(0, up_to + 1):
        if n - k <= 0:
            out.append((k, None))
            continue
        remaining = xs[k:]
        out.append((k, sum(remaining) / len(remaining)))
    return out


def time_segments(trades: list[BacktestTrade], *, buckets: int = 3) -> list[Segment]:
    """Split trades into contiguous time buckets and report expectancy per bucket."""
    if buckets < 1 or not trades:
        return []
    ordered = sorted(trades, key=lambda t: t.entry_time)
    out: list[Segment] = []
    size = max(1, len(ordered) // buckets)
    for b in range(buckets):
        start = b * size
        end = len(ordered) if b == buckets - 1 else min(len(ordered), (b + 1) * size)
        chunk = ordered[start:end]
        if not chunk:
            continue
        nets = [float(t.net_pnl) for t in chunk]
        out.append(
            Segment(
                label=f"time_bucket_{b + 1}", trade_count=len(chunk),
                net_expectancy=sum(nets) / len(nets), net_pnl=sum(nets),
            )
        )
    return out


def cost_scenario_sweep(
    dataset: Dataset,
    *,
    backtest_config: BacktestConfig,
    indicator_config: IndicatorConfig,
    strategy_config: StrategyConfig,
    cost_config: CostConfig,
    sizing_config: SizingConfig,
    risk_config: RiskConfig,
    paper_config: PaperConfig,
    symbols: list[Symbol] | None = None,
    min_operational_trades: int = 100,
) -> dict[str, Metrics]:
    """Re-run under optimistic/base/conservative and report metrics per scenario.

    A strategy that is positive ONLY under optimistic is NOT a success (§10).
    """
    from dataclasses import replace

    from backtesting.engine import run_backtest

    out: dict[str, Metrics] = {}
    for scenario in (CostScenario.OPTIMISTIC, CostScenario.BASE, CostScenario.CONSERVATIVE):
        result: BacktestResult = run_backtest(
            dataset,
            backtest_config=replace(backtest_config, cost_scenario=scenario),
            indicator_config=indicator_config, strategy_config=strategy_config,
            cost_config=cost_config, sizing_config=sizing_config,
            risk_config=risk_config, paper_config=paper_config, symbols=symbols,
        )
        out[scenario.value] = compute_metrics(
            result, min_operational_trades=min_operational_trades
        )
    return out


def parameter_perturbation(
    dataset: Dataset,
    *,
    backtest_config: BacktestConfig,
    indicator_config: IndicatorConfig,
    cost_config: CostConfig,
    sizing_config: SizingConfig,
    risk_config: RiskConfig,
    paper_config: PaperConfig,
    strategy_variants: list[tuple[str, StrategyConfig]],
    symbols: list[Symbol] | None = None,
    min_operational_trades: int = 100,
) -> list[tuple[str, Metrics]]:
    """Report metrics across a caller-supplied FIXED set of strategy variants.

    This is stability reporting, NOT optimization: the caller enumerates the
    variants and NO "best" is selected here (plan §7.1).
    """
    from backtesting.engine import run_backtest

    out: list[tuple[str, Metrics]] = []
    for label, variant in strategy_variants:
        result = run_backtest(
            dataset, backtest_config=backtest_config, indicator_config=indicator_config,
            strategy_config=variant, cost_config=cost_config, sizing_config=sizing_config,
            risk_config=risk_config, paper_config=paper_config, symbols=symbols,
        )
        out.append(
            (label, compute_metrics(result, min_operational_trades=min_operational_trades))
        )
    return out
