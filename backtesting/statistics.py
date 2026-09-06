"""Statistical validation (Phase 7) — pure-Python, seeded, deterministic.

Bootstrap confidence intervals, trade autocorrelation/dependency, and outlier
dependence (Master Plan §11). Each result carries an explicit "can / cannot
prove" note in the report.

CRITICAL (§11): a positive bootstrap CI is **necessary but NOT sufficient** — it
never renders an approval on its own. Trade count is an operational floor, not
significance. Correlated trades (see the autocorrelation result) can invalidate a
naive CI, so these outputs must be read together, never in isolation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BootstrapCI:
    point_estimate: float
    ci_low: float
    ci_high: float
    alpha: float
    iterations: int
    seed: int
    n: int
    positive: bool  # ci_low > 0 (necessary, NOT sufficient — §11)


@dataclass(frozen=True)
class OutlierDependence:
    expectancy_all: float | None
    top_removed: int
    expectancy_without_top: float | None
    still_positive: bool


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def bootstrap_mean_ci(
    values: list[float] | list[Decimal],
    *,
    seed: int,
    iterations: int = 10000,
    alpha: float = 0.05,
) -> BootstrapCI | None:
    """Percentile bootstrap CI for the mean. Deterministic under ``seed``."""
    xs = [float(v) for v in values]
    n = len(xs)
    if n == 0:
        return None
    point = sum(xs) / n
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += xs[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    low = _percentile(means, alpha / 2)
    high = _percentile(means, 1 - alpha / 2)
    return BootstrapCI(
        point_estimate=point, ci_low=low, ci_high=high, alpha=alpha,
        iterations=iterations, seed=seed, n=n, positive=low > 0.0,
    )


def lag1_autocorrelation(values: list[float] | list[Decimal]) -> float | None:
    """Lag-1 autocorrelation of the (time-ordered) trade PnL sequence.

    Near 0 ⇒ trades look independent; large magnitude ⇒ dependence that
    invalidates naive i.i.d. statistics (bootstrap, Monte Carlo).
    """
    xs = [float(v) for v in values]
    n = len(xs)
    if n < 3:
        return None
    mean = sum(xs) / n
    denom = sum((x - mean) ** 2 for x in xs)
    if denom == 0:
        return None
    num = sum((xs[i] - mean) * (xs[i + 1] - mean) for i in range(n - 1))
    return num / denom


def outlier_dependence(
    values: list[float] | list[Decimal], *, top_removed: int = 3
) -> OutlierDependence:
    """Expectancy after removing the best ``top_removed`` trades (§10 / §11)."""
    xs = [float(v) for v in values]
    n = len(xs)
    exp_all = (sum(xs) / n) if n else None
    if n <= top_removed:
        return OutlierDependence(exp_all, top_removed, None, False)
    trimmed = sorted(xs)[: n - top_removed]  # drop the largest `top_removed`
    exp_trim = sum(trimmed) / len(trimmed)
    return OutlierDependence(exp_all, top_removed, exp_trim, exp_trim > 0.0)
