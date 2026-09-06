"""Backtest persistence + operational-table isolation (plan §26/§30)."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from app.config import load_settings
from app.models import (
    BacktestRunRecord,
    PaperFillRecord,
    PaperOrderRecord,
    PortfolioSnapshotRecord,
    PositionRecord,
    RiskDecisionRecord,
)
from backtesting.metrics import compute_metrics
from backtesting.store import persist_backtest
from tests.fixtures.backtest_data import build_dataset, run_fixture_backtest

_OPERATIONAL = [
    PositionRecord,
    PortfolioSnapshotRecord,
    PaperOrderRecord,
    PaperFillRecord,
    RiskDecisionRecord,
]


def test_persist_writes_artifacts_and_index_row_only(db, tmp_path) -> None:
    _engine, session_factory, _url = db
    settings = load_settings(_env_file=None, environment="test")
    result = run_fixture_backtest(build_dataset(), settings)
    metrics = compute_metrics(result, min_operational_trades=5)

    run_id = persist_backtest(
        result, metrics, session_factory=session_factory, artifacts_dir=str(tmp_path)
    )

    base = Path(tmp_path) / run_id
    for fname in ("manifest.json", "metrics.json", "summary.json", "report.md",
                  "trades.csv", "equity.csv"):
        assert (base / fname).is_file(), f"missing artifact {fname}"

    # backtest_runs has exactly one row; operational tables are untouched.
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BacktestRunRecord)) == 1
        for model in _OPERATIONAL:
            assert session.scalar(select(func.count()).select_from(model)) == 0, (
                f"backtester must not write operational table {model.__tablename__}"
            )


def test_report_carries_disclaimer_and_survivorship_note(db, tmp_path) -> None:
    _engine, session_factory, _url = db
    settings = load_settings(_env_file=None, environment="test")
    result = run_fixture_backtest(build_dataset(), settings)
    metrics = compute_metrics(result, min_operational_trades=5)
    run_id = persist_backtest(
        result, metrics, session_factory=session_factory, artifacts_dir=str(tmp_path)
    )
    report = (Path(tmp_path) / run_id / "report.md").read_text(encoding="utf-8")
    assert "Pure-quant core only" in report  # §21 disclaimer
    assert "survived universe" in report.lower()  # §8.1 survivorship note
    summary = json.loads((Path(tmp_path) / run_id / "summary.json").read_text(encoding="utf-8"))
    assert summary["is_approval"] is False  # a backtest never renders an approval


def test_run_manifest_is_reproducible(db, tmp_path) -> None:
    _engine, session_factory, _url = db
    settings = load_settings(_env_file=None, environment="test")
    ds = build_dataset()
    r1 = run_fixture_backtest(ds, settings)
    r2 = run_fixture_backtest(ds, settings)
    assert r1.manifest.dataset_hash == r2.manifest.dataset_hash
    assert r1.manifest.config_snapshot == r2.manifest.config_snapshot
