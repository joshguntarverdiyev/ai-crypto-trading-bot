"""Phase 9 validation metrics + objective, pre-registered gates (pure-Python).

Reads ONLY a single run's own database (no cross-run aggregation — §26.6). Reuses
the frozen P7 pure-Python evidence tooling (``backtesting/metrics.py`` /
``statistics.py`` / ``robustness.py`` / ``walkforward.py``) verbatim by building a
``BacktestResult``-shaped view over the live run's snapshots + reconstructed
trades. No numpy/scipy/pandas.

Accounting (§35.5): the authoritative equity/return series comes from the
consolidated ``portfolio_snapshots`` (fully fee-inclusive), while per-CLOSED-trade
net P&L is reconstructed **fee-exact** from the fills' cash flows
(``exit_cash - entry_cost``, both fees included) — NOT ``ledger.realized_pnl``
(which omits the entry fee). Descriptive metrics are separated from statistical
evidence, which is separated from operational duration; no single number approves
a run and no profitability is claimed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.models import (
    PaperDecisionRecord,
    PaperFillRecord,
    PaperOrderRecord,
    PortfolioSnapshotRecord,
)
from app.paper.config import PaperValidationConfig
from app.time_utils import ensure_utc
from backtesting.metrics import Metrics, compute_metrics
from backtesting.robustness import (
    MonteCarloDrawdown,
    monte_carlo_max_drawdown,
    time_segments,
    trade_removal_curve,
)
from backtesting.statistics import (
    BootstrapCI,
    OutlierDependence,
    bootstrap_mean_ci,
    lag1_autocorrelation,
    outlier_dependence,
)
from backtesting.walkforward import PreRegistration, assert_thresholds_preregistered


# --- BacktestResult-shaped view (duck-typed for the P7 functions) ------------
@dataclass(frozen=True)
class _EquityPoint:
    equity: Decimal


@dataclass(frozen=True)
class _Trade:
    entry_time: datetime
    gross_pnl: Decimal
    net_pnl: Decimal
    symbol: str = ""


@dataclass(frozen=True)
class PaperResultView:
    starting_equity: Decimal
    ending_equity: Decimal
    equity_curve: list[_EquityPoint]
    trades: list[_Trade]
    net_pnls: list[Decimal] = field(default_factory=list)


# --- trade reconstruction (fee-exact, from the fills ledger) -----------------
def reconstruct_trades(run_sf: sessionmaker[Session]) -> list[_Trade]:
    """Reconstruct CLOSED round-trip trades per symbol from orders + fills.

    A trade closes when running inventory returns to <= 0. ``net_pnl`` is the exact
    round-trip cash delta (both entry and exit fees included); ``gross_pnl`` excludes
    fees. Long-only; handles add-ons and partial fills via running inventory.
    """
    trades: list[_Trade] = []
    with session_scope(run_sf) as session:
        orders = session.scalars(
            select(PaperOrderRecord).order_by(
                PaperOrderRecord.symbol, PaperOrderRecord.decision_time, PaperOrderRecord.created_at
            )
        ).all()
        fills_by_order: dict[str, list[PaperFillRecord]] = {}
        for f in session.scalars(select(PaperFillRecord)).all():
            fills_by_order.setdefault(f.order_id, []).append(f)

        by_symbol: dict[str, list[PaperOrderRecord]] = {}
        for o in orders:
            by_symbol.setdefault(o.symbol, []).append(o)

        for sym, sym_orders in by_symbol.items():
            open_qty = Decimal(0)
            entry_cost = Decimal(0)  # cash out (incl entry fees)
            entry_gross = Decimal(0)
            exit_cash = Decimal(0)  # cash in (net of exit fees)
            exit_gross = Decimal(0)
            entry_time: datetime | None = None
            for o in sym_orders:
                for f in fills_by_order.get(o.id, []):
                    if o.side == "buy":
                        if open_qty <= 0:
                            entry_time = ensure_utc(o.decision_time)
                        open_qty += f.fill_qty
                        entry_cost += f.fill_qty * f.fill_price + f.fee
                        entry_gross += f.fill_qty * f.fill_price
                    else:  # sell / exit
                        open_qty -= f.fill_qty
                        exit_cash += f.fill_qty * f.fill_price - f.fee
                        exit_gross += f.fill_qty * f.fill_price
                if open_qty <= 0 and entry_time is not None and (entry_cost > 0 or exit_cash > 0):
                    trades.append(
                        _Trade(
                            entry_time=entry_time,
                            gross_pnl=exit_gross - entry_gross,
                            net_pnl=exit_cash - entry_cost,
                            symbol=sym,
                        )
                    )
                    open_qty = Decimal(0)
                    entry_cost = entry_gross = exit_cash = exit_gross = Decimal(0)
                    entry_time = None
    return trades


def equity_curve(run_sf: sessionmaker[Session], *, primary_tf_seconds: int) -> list[_EquityPoint]:
    """Authoritative equity curve: the LAST snapshot per primary-timeframe boundary
    (the consolidated full-mark snapshot wins its per-tick sibling — §35.6)."""
    with session_scope(run_sf) as session:
        snaps = session.scalars(
            select(PortfolioSnapshotRecord).order_by(PortfolioSnapshotRecord.snapshot_time)
        ).all()
        by_bucket: dict[int, Decimal] = {}
        for s in snaps:
            epoch = int(ensure_utc(s.snapshot_time).timestamp())
            bucket = epoch // primary_tf_seconds
            by_bucket[bucket] = s.equity  # later snapshot in the bucket overwrites
    return [_EquityPoint(equity=by_bucket[b]) for b in sorted(by_bucket)]


def build_view(
    run_sf: sessionmaker[Session], *, starting_equity: Decimal, primary_tf_seconds: int
) -> PaperResultView:
    curve = equity_curve(run_sf, primary_tf_seconds=primary_tf_seconds)
    trades = reconstruct_trades(run_sf)
    ending = curve[-1].equity if curve else starting_equity
    return PaperResultView(
        starting_equity=starting_equity,
        ending_equity=ending,
        equity_curve=curve,
        trades=trades,
        net_pnls=[t.net_pnl for t in trades],
    )


# --- operational duration accounting (§35.9) ---------------------------------
@dataclass(frozen=True)
class DurationStats:
    calendar_days: float
    expected_boundaries: int
    processed_boundaries: int
    gap_boundaries: int
    unusable_boundaries: int
    uptime_fraction: float
    data_quality_fraction: float


def duration_stats(run_sf: sessionmaker[Session], *, primary_tf_seconds: int) -> DurationStats:
    with session_scope(run_sf) as session:
        # decision_time may repeat per symbol; collapse to distinct boundaries.
        times = sorted({ensure_utc(dt) for dt in
                        session.scalars(select(PaperDecisionRecord.decision_time)).all()})
        unusable_times = {
            ensure_utc(r.decision_time)
            for r in session.scalars(
                select(PaperDecisionRecord).where(
                    PaperDecisionRecord.reason == "unusable_or_stale"
                )
            ).all()
        }
    processed = len(times)
    if processed == 0:
        return DurationStats(0.0, 0, 0, 0, 0, 0.0, 0.0)
    span = (times[-1] - times[0]).total_seconds()
    expected = int(span // primary_tf_seconds) + 1
    gaps = max(0, expected - processed)
    unusable = len(unusable_times)
    return DurationStats(
        calendar_days=span / 86400.0,
        expected_boundaries=expected,
        processed_boundaries=processed,
        gap_boundaries=gaps,
        unusable_boundaries=unusable,
        uptime_fraction=(processed / expected) if expected else 0.0,
        data_quality_fraction=((processed - unusable) / processed) if processed else 0.0,
    )


# --- per-symbol concentration (P9 redesign multi-symbol) ---------------------
def per_symbol_net_pnl(trades: list[_Trade]) -> dict[str, Decimal]:
    """Net P&L attributed to each symbol across CLOSED trades."""
    out: dict[str, Decimal] = {}
    for t in trades:
        out[t.symbol] = out.get(t.symbol, Decimal(0)) + t.net_pnl
    return out


def max_symbol_concentration(trades: list[_Trade]) -> float | None:
    """Largest single-symbol share of TOTAL POSITIVE net P&L (a portfolio-
    concentration signal; None when there is no positive P&L). A value near 1.0
    means one symbol dominates the paper result — reported, never auto-PASS."""
    by_symbol = per_symbol_net_pnl(trades)
    positive = {s: p for s, p in by_symbol.items() if p > 0}
    total = sum(positive.values(), Decimal(0))
    if total <= 0:
        return None
    return float(max(positive.values()) / total)


# --- pre-registration (§35.4) ------------------------------------------------
def preregistration(run_id: str, cfg: PaperValidationConfig) -> PreRegistration:
    """Lock the objective gate thresholds BEFORE results are read (curve-fit guard)."""
    thresholds = {
        "min_operational_days": float(cfg.min_operational_days),
        "min_uptime_fraction": float(cfg.min_uptime_fraction),
        "max_unexplained_gaps": float(cfg.max_unexplained_gaps),
        "min_meaningful_trades": float(cfg.min_meaningful_trades),
        "min_trades_per_regime_cell": float(cfg.min_trades_per_regime_cell),
        "rolling_buckets": float(cfg.rolling_buckets),
        "concentration_top_k": float(cfg.concentration_top_k),
        "mc_max_drawdown_ceiling": float(cfg.mc_max_drawdown_ceiling),
        # P9 redesign: window + universe + Claude budget are pre-registered too.
        "validation_days": float(cfg.validation_days),
        "universe_max_symbols": float(cfg.universe_max_symbols),
        "claude_max_per_boundary": float(cfg.claude_max_per_boundary),
        "claude_max_per_run": float(cfg.claude_max_per_run),
    }
    return PreRegistration(
        dataset_hash=hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
        seed=cfg.seed,
        hypotheses=(
            "P9 measures operational robustness + accumulates statistical evidence; "
            "it never proves profitability and never implies live readiness.",
        ),
        thresholds=thresholds,
        splits={},
    )


# --- regime coverage (per CLOSED trade's entry-boundary regime) --------------
def trade_regime_counts(
    run_sf: sessionmaker[Session], trades: list[_Trade]
) -> dict[str, int]:
    """Count CLOSED trades per entry-boundary regime label.

    Each trade is attributed to the descriptive regime that was recorded at its
    ENTRY boundary (``paper_decisions.regime`` at ``(entry_time, symbol)``). Trades
    with no recorded regime are omitted. Trade-level (not decision-level) counting
    is what the regime-coverage gate requires (§35.4)."""
    counts: dict[str, int] = {}
    with session_scope(run_sf) as session:
        for t in trades:
            row = session.scalars(
                select(PaperDecisionRecord.regime).where(
                    PaperDecisionRecord.decision_time == t.entry_time,
                    PaperDecisionRecord.symbol == t.symbol,
                )
            ).first()
            if row is None:
                continue
            counts[row] = counts.get(row, 0) + 1
    return counts


def regime_coverage_status(counts: dict[str, int], *, min_per_cell: int) -> tuple[str, str]:
    """Objective regime-coverage status (§35.4).

    * ``insufficient_data`` if there are not enough attributed trades to fill even a
      single cell (so "observed once" can NEVER pass).
    * ``pass`` if at least one regime cell has ``>= min_per_cell`` trades.
    * ``fail`` if there are enough trades overall but no cell reaches the threshold.
    """
    total = sum(counts.values())
    if total < min_per_cell:
        return "insufficient_data", (
            f"{total} regime-attributed trades < {min_per_cell} (cannot fill any cell)"
        )
    covered = [k for k, v in counts.items() if v >= min_per_cell]
    if covered:
        return "pass", f"{len(covered)} regime cell(s) with >= {min_per_cell} trades"
    return "fail", f"no regime cell reached {min_per_cell} trades (observed-once never counts)"


# --- rolling expectancy stability (§35.4; reuses P7 time_segments) ------------
def _sign(x: float) -> int:
    return 1 if x > 0 else -1


def rolling_expectancy_stability(
    trades: list[_Trade], *, buckets: int, min_trades: int
) -> tuple[str, str]:
    """Chronological rolling-expectancy sign-stability across ``buckets`` contiguous
    buckets (reuses the frozen P7 ``time_segments``). Deterministic; no tuning.

    * ``insufficient_data`` if fewer than ``min_trades`` trades or fewer than
      ``buckets`` non-empty buckets form.
    * ``pass`` if every bucket's expectancy shares the same sign (stable).
    * ``fail`` if the expectancy sign flips across buckets (unstable).
    """
    if len(trades) < min_trades:
        return "insufficient_data", f"{len(trades)} trades < {min_trades}"
    segs = time_segments(trades, buckets=buckets)  # type: ignore[arg-type]  # _Trade duck-typed
    if len(segs) < buckets:
        return "insufficient_data", f"only {len(segs)} non-empty buckets < {buckets}"
    signs = {_sign(s.net_expectancy) for s in segs if s.net_expectancy is not None}
    if len(signs) <= 1:
        return "pass", f"expectancy sign stable across {len(segs)} buckets"
    return "fail", f"expectancy sign flips across {len(segs)} buckets"


# --- top-k concentration (§35.4; reuses P7 trade_removal_curve) ---------------
def top_k_concentration(
    net_pnls: list[Decimal], *, k: int, min_trades: int
) -> tuple[str, str]:
    """Whether performance depends excessively on the best ``k`` trades (reuses the
    frozen P7 ``trade_removal_curve``). Deterministic; no tuning.

    * ``insufficient_data`` if fewer than ``min_trades`` trades or ``n <= k``.
    * ``fail`` (excessive) if expectancy is positive overall but turns non-positive
      after removing the best ``k`` trades.
    * ``pass`` otherwise (not outlier-dependent, or not positive to begin with).
    """
    n = len(net_pnls)
    if n < min_trades or n <= k:
        return "insufficient_data", f"{n} trades (need >= {max(min_trades, k + 1)})"
    curve = trade_removal_curve(net_pnls, up_to=k)
    exp_all = curve[0][1]
    exp_k = curve[k][1]
    if exp_all is None or exp_k is None:
        return "insufficient_data", "expectancy undefined"
    if exp_all > 0 and exp_k <= 0:
        return "fail", f"expectancy {exp_all:.6g} → {exp_k:.6g} after removing top {k} (excessive)"
    return "pass", f"expectancy {exp_all:.6g} → {exp_k:.6g} after removing top {k}"


# --- Monte-Carlo max-drawdown ceiling (§35.4) --------------------------------
def monte_carlo_drawdown_status(
    mc: MonteCarloDrawdown | None, *, ceiling: float
) -> tuple[str, str]:
    """Objective gate on the (seeded, deterministic) Monte-Carlo max-drawdown vs a
    PRE-REGISTERED ceiling. Compares the p95 statistic from the existing
    ``monte_carlo_max_drawdown`` (methodology unchanged).

    * ``insufficient_data`` if the MC statistic could not be computed (< 2 trades).
    * ``pass`` if ``p95 <= ceiling``.
    * ``fail`` if ``p95 > ceiling``.
    """
    if mc is None:
        return "insufficient_data", "Monte-Carlo drawdown undefined (need >= 2 trades)"
    if mc.p95 <= ceiling:
        return "pass", f"MC drawdown p95 {mc.p95:.4f} <= ceiling {ceiling:.4f} (p99={mc.p99:.4f})"
    return "fail", f"MC drawdown p95 {mc.p95:.4f} > ceiling {ceiling:.4f} (p99={mc.p99:.4f})"


# --- full evidence set + gate evaluation -------------------------------------
@dataclass(frozen=True)
class GateResult:
    name: str
    status: str  # pass | fail | insufficient_data
    detail: str


@dataclass(frozen=True)
class ValidationEvidence:
    metrics: Metrics
    bootstrap: BootstrapCI | None
    autocorrelation: float | None
    outlier: OutlierDependence
    monte_carlo_drawdown: MonteCarloDrawdown | None
    duration: DurationStats
    regime_coverage: dict[str, int]
    gates: list[GateResult]
    prereg_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "metrics": self.metrics.to_dict(),
            "bootstrap_positive": None if self.bootstrap is None else self.bootstrap.positive,
            "autocorrelation": self.autocorrelation,
            "outlier_still_positive": self.outlier.still_positive,
            "monte_carlo_dd_p95": None
            if self.monte_carlo_drawdown is None
            else self.monte_carlo_drawdown.p95,
            "duration": self.duration.__dict__,
            "regime_coverage": self.regime_coverage,
            "gates": [g.__dict__ for g in self.gates],
            "prereg_digest": self.prereg_digest,
        }


def evaluate(
    run_sf: sessionmaker[Session], cfg: PaperValidationConfig, run_id: str
) -> ValidationEvidence:
    """Compute the full evidence set and objective, pre-registered gate statuses.

    No single metric approves the run; profitability is never asserted. Statistical
    gates are 'evidence readiness' (not significance) and are read together with
    their guardrails (autocorrelation can invalidate a naive bootstrap/MC).
    """
    prereg = preregistration(run_id, cfg)
    # Guard against post-hoc threshold tuning (uses == the pre-registered values).
    assert_thresholds_preregistered(prereg, prereg.thresholds)

    tf_secs = cfg.primary_timeframe.seconds
    view = build_view(run_sf, starting_equity=cfg.starting_equity, primary_tf_seconds=tf_secs)
    # PaperResultView is duck-typed to the fields compute_metrics reads (§35.5).
    metrics = compute_metrics(view, min_operational_trades=cfg.min_meaningful_trades)  # type: ignore[arg-type]
    net = view.net_pnls
    boot = bootstrap_mean_ci(net, seed=cfg.seed) if net else None
    autocorr = lag1_autocorrelation(net)
    outlier = outlier_dependence(net)
    mc_dd = monte_carlo_max_drawdown(net, cfg.starting_equity, seed=cfg.seed) if net else None
    dur = duration_stats(run_sf, primary_tf_seconds=tf_secs)
    regimes = trade_regime_counts(run_sf, view.trades)

    gates: list[GateResult] = []

    # G-OPERATIONAL
    gates.append(
        GateResult(
            "operational_duration",
            "pass" if dur.calendar_days >= cfg.min_operational_days else "fail",
            f"{dur.calendar_days:.1f}d >= {cfg.min_operational_days}d",
        )
    )
    gates.append(
        GateResult(
            "uptime",
            "pass" if dur.uptime_fraction >= cfg.min_uptime_fraction else "fail",
            f"{dur.uptime_fraction:.4f} >= {cfg.min_uptime_fraction}",
        )
    )
    gates.append(
        GateResult(
            "unexplained_gaps",
            "pass" if dur.gap_boundaries <= cfg.max_unexplained_gaps else "fail",
            f"{dur.gap_boundaries} <= {cfg.max_unexplained_gaps}",
        )
    )

    # G-STATISTICAL
    gates.append(
        GateResult(
            "meaningful_trades",
            "pass" if not metrics.sample_below_min else "fail",
            f"{metrics.trade_count} >= {cfg.min_meaningful_trades}",
        )
    )
    rc_status, rc_detail = regime_coverage_status(
        regimes, min_per_cell=cfg.min_trades_per_regime_cell
    )
    gates.append(GateResult("regime_coverage", rc_status, rc_detail))
    gates.append(
        GateResult(
            "independence_for_naive_stats",
            "pass" if (autocorr is None or abs(autocorr) <= 0.2)
            else "fail",
            f"lag1 autocorrelation={autocorr} (|rho|<=0.2 for naive bootstrap/MC validity)",
        )
    )
    gates.append(
        GateResult(
            "outlier_dependence",
            "insufficient_data" if outlier.expectancy_without_top is None
            else ("pass" if outlier.still_positive else "fail"),
            "expectancy remains positive after removing the best trades",
        )
    )
    rs_status, rs_detail = rolling_expectancy_stability(
        view.trades, buckets=cfg.rolling_buckets, min_trades=cfg.min_meaningful_trades
    )
    gates.append(GateResult("rolling_expectancy_stability", rs_status, rs_detail))
    ck_status, ck_detail = top_k_concentration(
        net, k=cfg.concentration_top_k, min_trades=cfg.min_meaningful_trades
    )
    gates.append(GateResult("top_k_concentration", ck_status, ck_detail))
    dd_status, dd_detail = monte_carlo_drawdown_status(
        mc_dd, ceiling=cfg.mc_max_drawdown_ceiling
    )
    gates.append(GateResult("monte_carlo_drawdown_ceiling", dd_status, dd_detail))

    return ValidationEvidence(
        metrics=metrics,
        bootstrap=boot,
        autocorrelation=autocorr,
        outlier=outlier,
        monte_carlo_drawdown=mc_dd,
        duration=dur,
        regime_coverage=regimes,
        gates=gates,
        prereg_digest=prereg.digest,
    )


def evidence_json(evidence: ValidationEvidence) -> str:
    return json.dumps(evidence.to_dict(), default=str, sort_keys=True)
