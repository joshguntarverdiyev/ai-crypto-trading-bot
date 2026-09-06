"""Performance metrics (Phase 7) — pure-Python, deterministic.

Computes the descriptive metric set (Master Plan §11 / §17) from a
``BacktestResult``. No numpy/scipy/pandas (stdlib ``math``/``statistics`` only).

Every metric is *supporting evidence*, not a gate: no single number renders an
"approve" (§11). Sample size is an operational floor, NOT statistical
significance. Ratios (Sharpe/Sortino/Calmar) assume i.i.d.-ish returns and a
stated annualization — cross-check with the robustness/statistics modules before
trusting them.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from decimal import Decimal

from backtesting.models import BacktestResult

HOURS_PER_YEAR = 24 * 365  # 1h-bar annualization factor


@dataclass(frozen=True)
class Metrics:
    trade_count: int
    sample_below_min: bool
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    profit_factor: float | None
    net_expectancy: float | None
    gross_pnl: float
    net_pnl: float
    total_return: float
    max_drawdown: float
    max_drawdown_duration_bars: int
    volatility_annual: float | None
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    periods: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _equity_returns(equity: list[Decimal]) -> list[float]:
    out: list[float] = []
    for prev, cur in zip(equity, equity[1:], strict=False):
        if prev > 0:
            out.append(float(cur / prev) - 1.0)
    return out


def _max_drawdown(equity: list[Decimal]) -> tuple[float, int]:
    """Return (max fractional drawdown, longest underwater run in bars)."""
    peak = None
    max_dd = 0.0
    underwater = 0
    longest = 0
    for eq in equity:
        if peak is None or eq > peak:
            peak = eq
            underwater = 0
        else:
            underwater += 1
            longest = max(longest, underwater)
            if peak and peak > 0:
                dd = float((peak - eq) / peak)
                max_dd = max(max_dd, dd)
    return max_dd, longest


def compute_metrics(
    result: BacktestResult,
    *,
    min_operational_trades: int = 100,
    periods_per_year: int = HOURS_PER_YEAR,
    risk_free_rate: float = 0.0,
) -> Metrics:
    net = [float(p) for p in result.net_pnls]
    gross = [float(t.gross_pnl) for t in result.trades]
    wins = [p for p in net if p > 0]
    losses = [p for p in net if p < 0]
    n = len(net)

    win_rate = (len(wins) / n) if n else None
    avg_win = (sum(wins) / len(wins)) if wins else None
    avg_loss = (sum(losses) / len(losses)) if losses else None
    loss_sum = abs(sum(losses))
    profit_factor = (sum(wins) / loss_sum) if loss_sum > 0 else None
    net_expectancy = (sum(net) / n) if n else None

    start = float(result.starting_equity)
    end = float(result.ending_equity)
    total_return = (end / start - 1.0) if start > 0 else 0.0

    equity = [p.equity for p in result.equity_curve]
    max_dd, dd_dur = _max_drawdown(equity)
    returns = _equity_returns(equity)
    periods = len(returns)
    ppy = periods_per_year
    rf_per = risk_free_rate / ppy

    vol_annual: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    if periods >= 2:
        stdev = statistics.pstdev(returns)
        mean_excess = statistics.fmean(returns) - rf_per
        vol_annual = stdev * math.sqrt(ppy)
        if stdev > 0:
            sharpe = (mean_excess / stdev) * math.sqrt(ppy)
        downside = [min(0.0, r - rf_per) for r in returns]
        dstd = math.sqrt(sum(d * d for d in downside) / len(downside))
        if dstd > 0:
            sortino = (mean_excess / dstd) * math.sqrt(ppy)

    calmar: float | None = None
    if periods >= 1 and max_dd > 0 and start > 0 and end > 0:
        cagr = (end / start) ** (ppy / periods) - 1.0
        calmar = cagr / max_dd

    return Metrics(
        trade_count=n,
        sample_below_min=n < min_operational_trades,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        net_expectancy=net_expectancy,
        gross_pnl=sum(gross),
        net_pnl=sum(net),
        total_return=total_return,
        max_drawdown=max_dd,
        max_drawdown_duration_bars=dd_dur,
        volatility_annual=vol_annual,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        periods=periods,
    )
