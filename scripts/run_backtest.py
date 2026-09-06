"""Run a deterministic, offline pure-quant backtest (Phase 7).

Offline research tooling only — no trading, no calibration, no edge claim. Loads a
committed OHLCV snapshot from ``<BACKTEST_ARTIFACTS_DIR>/datasets/<name>``, replays
it through the frozen P2→P6 contracts, writes artifacts + a ``backtest_runs`` row,
and prints the evidence-set summary. Run with the project virtualenv active:

    python -m scripts.run_backtest

Dataset layout (per symbol/timeframe CSV): see ``backtesting.dataset``.
"""

from __future__ import annotations

from pathlib import Path

from app.config import load_settings
from app.database import init_db, make_engine, make_session_factory
from app.logging_config import configure_logging
from app.market_data.models import Symbol, Timeframe
from backtesting.dataset import load_dataset
from backtesting.engine import run_backtest
from backtesting.metrics import compute_metrics
from backtesting.models import BacktestDataError
from backtesting.report import build_markdown_report
from backtesting.store import persist_backtest


def main() -> None:
    settings = load_settings()
    configure_logging(settings)
    bt = settings.backtest_config()

    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    datasets_root = Path(bt.artifacts_dir) / "datasets"
    symbols = [Symbol.parse(s) for s in settings.market_symbols]
    timeframes = [Timeframe(t) for t in settings.market_timeframes]

    try:
        dataset = load_dataset(
            datasets_root, bt.dataset_name, symbols=symbols, timeframes=timeframes
        )
    except BacktestDataError as exc:
        print(f"Could not load dataset {bt.dataset_name!r} from {datasets_root}:\n  {exc}")
        print(
            "Place a committed OHLCV snapshot there (offline; no network fetch). "
            "See backtesting.dataset for the CSV layout."
        )
        return

    result = run_backtest(
        dataset,
        backtest_config=bt,
        indicator_config=settings.indicator_config(),
        strategy_config=settings.strategy_config(),
        cost_config=settings.cost_config(),
        sizing_config=settings.sizing_config(),
        risk_config=settings.risk_config(),
        paper_config=settings.paper_config(),
        symbols=symbols,
    )
    metrics = compute_metrics(result, min_operational_trades=bt.min_operational_trades)
    run_id = persist_backtest(
        result, metrics, session_factory=session_factory, artifacts_dir=bt.artifacts_dir
    )
    print(build_markdown_report(result, metrics))
    print(f"\nArtifacts + backtest_runs row written. run_id={run_id}")


if __name__ == "__main__":
    main()
