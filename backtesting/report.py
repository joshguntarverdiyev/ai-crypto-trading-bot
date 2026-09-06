"""Backtest report builder (Phase 7) — pure text/dict, deterministic.

Emits an EVIDENCE SET, never a boolean "approve" (Master Plan §11). Every report
carries the standard pure-quant disclaimer (§21) and the survivorship/universe
note (§8.1), and prints per-metric "can / cannot prove" framing plus robustness
interpretation guardrails.
"""

from __future__ import annotations

from typing import Any

from backtesting.metrics import Metrics
from backtesting.models import BacktestResult

# §21 — mandatory on every report.
STANDARD_DISCLAIMER = (
    "Pure-quant core only. Live/paper additionally applies the advisory Claude "
    "veto (HOLD-only) and the news pipeline, evaluated forward (P8+). These "
    "results are not, and cannot be, a news-enhanced historical backtest "
    "(Master Plan §8). Paper/live performance is never claimed to equal this. "
    "No edge or performance is claimed; a positive backtest is NOT proof of a "
    "tradable edge."
)

# §8.1 — mandatory universe/survivorship note.
SURVIVORSHIP_NOTE = (
    "Universe: a FIXED two-asset survived universe (BTC/USDT, ETH/USDT). No "
    "delisted/dead assets are included; results are NOT claimed to generalize to "
    "the broader crypto market. This is an explicitly reported limitation."
)

# §17 — per-metric framing (proves / does not prove / role).
METRIC_MEANINGS: dict[str, tuple[str, str, str]] = {
    "trade_count": ("sample floor met", "statistical significance", "operational minimum only"),
    "net_expectancy": ("avg net PnL/trade", "stability/repeatability", "supporting"),
    "win_rate": ("share of winners", "edge (payoff matters)", "supporting"),
    "profit_factor": ("gross win/loss ratio", "an edge (not a magic gate)", "supporting"),
    "max_drawdown": ("worst peak-to-trough", "future drawdown", "risk context"),
    "sharpe": ("risk-adjusted return", "tail safety / non-normality", "supporting"),
    "sortino": ("downside-adjusted return", "tail safety", "supporting"),
    "calmar": ("return vs max DD", "forward performance", "supporting"),
}


def _fmt(x: Any) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.6f}"
    return str(x)


def build_summary(result: BacktestResult, metrics: Metrics) -> dict[str, Any]:
    """A JSON-serializable summary for ``backtest_runs.summary_metrics``."""
    return {
        "metrics": metrics.to_dict(),
        "starting_equity": str(result.starting_equity),
        "ending_equity": str(result.ending_equity),
        "final_kill_status": result.final_kill_status,
        "event_count": len(result.events),
        "disclaimer": STANDARD_DISCLAIMER,
        "survivorship_note": SURVIVORSHIP_NOTE,
        "is_approval": False,  # a backtest NEVER renders an approval (§11)
    }


def build_markdown_report(
    result: BacktestResult,
    metrics: Metrics,
    *,
    extras: dict[str, Any] | None = None,
) -> str:
    """Render a human-readable evidence-set report (deterministic)."""
    m = result.manifest
    lines: list[str] = []
    lines.append("# Backtest Report (pure-quant; NO edge claim)")
    lines.append("")
    lines.append(f"> {STANDARD_DISCLAIMER}")
    lines.append("")
    lines.append(f"> {SURVIVORSHIP_NOTE}")
    lines.append("")
    lines.append("## Run")
    lines.append(f"- dataset: `{m.dataset_name}`  hash: `{m.dataset_hash}`")
    lines.append(f"- symbols: {', '.join(m.symbols)}")
    lines.append(f"- range: {m.range_start} .. {m.range_end}")
    lines.append(f"- cost_scenario: {m.cost_scenario}  entry_fill_rule: {m.entry_fill_rule}")
    lines.append(f"- halt_policy: {m.halt_policy}  seed: {m.seed}")
    lines.append(f"- engine: {m.engine_version}  strategy: {m.strategy_version}")
    lines.append(f"- final_kill_status: {result.final_kill_status}")
    lines.append("")
    lines.append("## Metrics (evidence set — NOT an approval)")
    md = metrics.to_dict()
    for key, value in md.items():
        meaning = METRIC_MEANINGS.get(key)
        suffix = (
            f"  _(proves: {meaning[0]}; not: {meaning[1]}; role: {meaning[2]})_"
            if meaning
            else ""
        )
        lines.append(f"- **{key}**: {_fmt(value)}{suffix}")
    if metrics.sample_below_min:
        lines.append("")
        lines.append(
            "> WARNING: trade_count is below the operational minimum — treat all "
            "statistics as low-confidence (sample size is not significance)."
        )
    if extras:
        lines.append("")
        lines.append("## Supporting analyses (context — read together, never in isolation)")
        for name, value in extras.items():
            lines.append(f"- **{name}**: {value}")
    lines.append("")
    lines.append(
        "> Interpretation: no single metric or interval renders an approval "
        "(§11). A positive bootstrap CI is necessary, not sufficient; Monte Carlo "
        "reshuffle assumes trade independence — cross-check the autocorrelation "
        "result. Buy-and-hold is context, not a gate (§0.1-5)."
    )
    lines.append("")
    return "\n".join(lines)
