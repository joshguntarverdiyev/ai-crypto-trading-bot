"""Walk-forward / OOS harness + pre-registration (Phase 7).

Chronological train/validation/test splits and rolling walk-forward windows with
**parameter isolation** and a **pre-registration** discipline (Master Plan §10 /
§G): any numeric threshold must be fixed BEFORE the OOS result is read;
post-hoc thresholds are rejected. P7 ships the harness + a worked example and
does NOT declare an edge.

No time-shuffling: splits are strictly chronological.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from app.costs.config import CostConfig
from app.execution.config import PaperConfig
from app.indicators.config import IndicatorConfig
from app.market_data.models import RawCandle, Symbol, Timeframe
from app.risk.config import RiskConfig
from app.sizing.config import SizingConfig
from app.strategy.config import StrategyConfig
from backtesting.config import BacktestConfig
from backtesting.dataset import Dataset, dataset_from_raw
from backtesting.metrics import Metrics, compute_metrics
from backtesting.models import BacktestError


class PreRegistrationError(BacktestError):
    """A threshold was used that was not pre-registered before OOS (curve-fitting guard)."""


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime  # exclusive

    def contains(self, t: datetime) -> bool:
        return self.start <= t < self.end


@dataclass(frozen=True)
class PreRegistration:
    """Locked BEFORE OOS is read (§G threshold rule)."""

    dataset_hash: str
    seed: int
    hypotheses: tuple[str, ...]
    thresholds: dict[str, float]
    splits: dict[str, str]  # label -> "start/end" iso

    @property
    def digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WindowResult:
    in_sample: TimeRange
    oos: TimeRange
    oos_metrics: Metrics


@dataclass(frozen=True)
class WalkForwardReport:
    windows: list[WindowResult] = field(default_factory=list)


def assert_thresholds_preregistered(
    prereg: PreRegistration, used_thresholds: dict[str, float]
) -> None:
    """Raise if any used threshold was not pre-registered (or was retuned)."""
    for name, value in used_thresholds.items():
        if name not in prereg.thresholds:
            raise PreRegistrationError(
                f"threshold {name!r} was not pre-registered (post-hoc tuning forbidden)"
            )
        if prereg.thresholds[name] != value:
            raise PreRegistrationError(
                f"threshold {name!r} changed after pre-registration "
                f"({prereg.thresholds[name]} -> {value})"
            )


def _raw_from_candle(c) -> RawCandle:  # noqa: ANN001 (Candle)
    return RawCandle(
        source=c.source, symbol=str(c.symbol), timeframe=c.timeframe.value,
        open_time=c.open_time, open=format(c.open, "f"), high=format(c.high, "f"),
        low=format(c.low, "f"), close=format(c.close, "f"), volume=format(c.volume, "f"),
    )


def slice_dataset(dataset: Dataset, rng: TimeRange, *, name_suffix: str = "slice") -> Dataset:
    """Return a sub-dataset with candles whose ``open_time`` is in ``rng`` (chronological)."""
    raw_by_key: dict[tuple[Symbol, Timeframe], list[RawCandle]] = {}
    for (sym_str, tf_str), candles in dataset.series.items():
        symbol = Symbol.parse(sym_str)
        timeframe = Timeframe(tf_str)
        subset = [_raw_from_candle(c) for c in candles if rng.contains(c.open_time)]
        if subset:
            raw_by_key[(symbol, timeframe)] = subset
    return dataset_from_raw(f"{dataset.name}:{name_suffix}", raw_by_key)


def chronological_split(
    dataset: Dataset, *, train: float = 0.6, validation: float = 0.2, test: float = 0.2
) -> dict[str, TimeRange]:
    """Chronological train/validation/test ranges over the dataset span."""
    if dataset.range_start is None or dataset.range_end is None:
        raise BacktestError("dataset has no time range to split")
    if abs((train + validation + test) - 1.0) > 1e-9:
        raise ValueError("train + validation + test must sum to 1.0")
    start = dataset.range_start
    total = (dataset.range_end - start).total_seconds()
    t_end = start + _seconds(total * train)
    v_end = t_end + _seconds(total * validation)
    return {
        "train": TimeRange(start, t_end),
        "validation": TimeRange(t_end, v_end),
        "test": TimeRange(v_end, dataset.range_end),
    }


def _seconds(secs: float):  # noqa: ANN202
    from datetime import timedelta

    return timedelta(seconds=secs)


def walk_forward(
    dataset: Dataset,
    *,
    n_splits: int,
    backtest_config: BacktestConfig,
    indicator_config: IndicatorConfig,
    strategy_config: StrategyConfig,
    cost_config: CostConfig,
    sizing_config: SizingConfig,
    risk_config: RiskConfig,
    paper_config: PaperConfig,
    symbols: list[Symbol] | None = None,
    min_operational_trades: int = 100,
) -> WalkForwardReport:
    """Rolling walk-forward: evaluate FIXED parameters on successive OOS folds.

    Parameter isolation: parameters are NOT tuned per window (P7 does not tune);
    this measures out-of-sample stability of a fixed configuration.
    """
    from backtesting.engine import run_backtest

    if n_splits < 1:
        raise ValueError("n_splits must be >= 1")
    if dataset.range_start is None or dataset.range_end is None:
        raise BacktestError("dataset has no time range for walk-forward")
    start = dataset.range_start
    span = (dataset.range_end - start).total_seconds()
    fold = span / (n_splits + 1)

    windows: list[WindowResult] = []
    for i in range(1, n_splits + 1):
        is_range = TimeRange(start, start + _seconds(fold * i))
        oos_range = TimeRange(start + _seconds(fold * i), start + _seconds(fold * (i + 1)))
        try:
            oos_ds = slice_dataset(dataset, oos_range, name_suffix=f"oos{i}")
        except BacktestError:
            continue  # OOS fold too small to form a valid (contiguous) series
        result = run_backtest(
            oos_ds, backtest_config=backtest_config, indicator_config=indicator_config,
            strategy_config=strategy_config, cost_config=cost_config,
            sizing_config=sizing_config, risk_config=risk_config,
            paper_config=paper_config, symbols=symbols,
        )
        windows.append(
            WindowResult(
                in_sample=is_range, oos=oos_range,
                oos_metrics=compute_metrics(result, min_operational_trades=min_operational_trades),
            )
        )
    return WalkForwardReport(windows=windows)


__all__ = [
    "TimeRange",
    "PreRegistration",
    "PreRegistrationError",
    "WindowResult",
    "WalkForwardReport",
    "assert_thresholds_preregistered",
    "slice_dataset",
    "chronological_split",
    "walk_forward",
]
