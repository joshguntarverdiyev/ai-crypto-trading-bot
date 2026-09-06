"""Backtest persistence (Phase 7) — research index + filesystem artifacts.

Writes the full run artifacts (manifest, trades, equity curve, metrics, report)
under ``<artifacts_dir>/<run_id>/`` and a single ``backtest_runs`` index row. It
touches NO operational tables (positions/portfolio_snapshots/paper_orders/...)
and never writes a ``claude_decisions``/``news`` row — the backtester has no
Claude/news runtime and the sentinel verdict is never persisted (plan §21/§26).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.ids import new_id
from app.models import BacktestRunRecord
from backtesting.metrics import Metrics
from backtesting.models import BacktestResult
from backtesting.report import build_markdown_report, build_summary


def _write_artifacts(base: Path, result: BacktestResult, metrics: Metrics) -> None:
    base.mkdir(parents=True, exist_ok=True)
    m = result.manifest

    manifest_json = {
        "dataset_name": m.dataset_name,
        "dataset_hash": m.dataset_hash,
        "symbols": list(m.symbols),
        "timeframes": list(m.timeframes),
        "range_start": m.range_start.isoformat() if m.range_start else None,
        "range_end": m.range_end.isoformat() if m.range_end else None,
        "seed": m.seed,
        "cost_scenario": m.cost_scenario,
        "entry_fill_rule": m.entry_fill_rule,
        "halt_policy": m.halt_policy,
        "engine_version": m.engine_version,
        "indicator_set_version": m.indicator_set_version,
        "cost_model_version": m.cost_model_version,
        "strategy_version": m.strategy_version,
        "sizing_version": m.sizing_version,
        "risk_version": m.risk_version,
        "paper_version": m.paper_version,
        "config_snapshot": m.config_snapshot,
        "run_time": m.run_time.isoformat(),
    }
    (base / "manifest.json").write_text(json.dumps(manifest_json, indent=2), encoding="utf-8")
    (base / "metrics.json").write_text(json.dumps(metrics.to_dict(), indent=2, default=str),
                                       encoding="utf-8")
    (base / "summary.json").write_text(
        json.dumps(build_summary(result, metrics), indent=2, default=str), encoding="utf-8"
    )
    (base / "report.md").write_text(build_markdown_report(result, metrics), encoding="utf-8")

    with (base / "trades.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "symbol", "direction", "entry_time", "entry_price", "quantity", "entry_fee",
            "exit_time", "exit_price", "exit_fee", "exit_reason", "gross_pnl", "net_pnl",
            "bars_held",
        ])
        for t in result.trades:
            w.writerow([
                t.symbol, t.direction, t.entry_time.isoformat(), format(t.entry_price, "f"),
                format(t.quantity, "f"), format(t.entry_fee, "f"), t.exit_time.isoformat(),
                format(t.exit_price, "f"), format(t.exit_fee, "f"), t.exit_reason,
                format(t.gross_pnl, "f"), format(t.net_pnl, "f"), t.bars_held,
            ])

    with (base / "equity.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "equity", "cash", "open_positions"])
        for p in result.equity_curve:
            w.writerow([
                p.time.isoformat(), format(p.equity, "f"), format(p.cash, "f"),
                p.open_positions,
            ])


def persist_backtest(
    result: BacktestResult,
    metrics: Metrics,
    *,
    session_factory: sessionmaker[Session],
    artifacts_dir: str | Path,
    run_id: str | None = None,
) -> str:
    """Write artifacts + a ``backtest_runs`` row. Returns the run_id."""
    run_id = run_id or new_id()
    base = Path(artifacts_dir) / run_id
    _write_artifacts(base, result, metrics)

    m = result.manifest
    with session_scope(session_factory) as session:
        session.add(
            BacktestRunRecord(
                id=run_id, run_time=m.run_time, dataset_name=m.dataset_name,
                dataset_hash=m.dataset_hash, symbols=json.dumps(list(m.symbols)),
                timeframes=json.dumps(list(m.timeframes)),
                range_start=m.range_start, range_end=m.range_end, seed=m.seed,
                cost_scenario=m.cost_scenario, entry_fill_rule=m.entry_fill_rule,
                halt_policy=m.halt_policy, engine_version=m.engine_version,
                indicator_set_version=m.indicator_set_version,
                cost_model_version=m.cost_model_version, strategy_version=m.strategy_version,
                sizing_version=m.sizing_version, risk_version=m.risk_version,
                paper_version=m.paper_version,
                config_snapshot=json.dumps(m.config_snapshot),
                summary_metrics=json.dumps(build_summary(result, metrics), default=str),
                artifact_path=str(base), status="completed",
            )
        )
    return run_id
