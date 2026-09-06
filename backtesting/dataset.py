"""HistoricalDatasetLoader — offline, deterministic OHLCV snapshots (Phase 7).

No network fetch. Reads a committed/materialized CSV snapshot per
``(symbol, timeframe)`` and runs it through the EXISTING Phase 1 validation gate
so the backtest consumes the same ``Candle`` invariants and quality flags as
production. Fail-closed (§28): structurally-invalid rows or **gaps** reject the
dataset with a clear error rather than silently biasing results. A SHA-256
content hash over the normalized rows is recorded for reproducibility (§22).

CSV filename convention: ``<BASE>-<QUOTE>_<timeframe>.csv`` (e.g.
``BTC-USDT_1h.csv``), columns: ``open_time,open,high,low,close,volume`` with
``open_time`` an ISO-8601 UTC timestamp and money as plain strings (floats are
rejected downstream by the Phase 1 money contract).
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.market_data.models import Candle, RawCandle, Symbol, Timeframe
from app.market_data.service import MarketDataResult
from app.market_data.validation import ValidationResult, validate_candles
from backtesting.models import BacktestDataError

_COLUMNS = ("open_time", "open", "high", "low", "close", "volume")
_SOURCE = "backtest-fixture"
# Large staleness allowance: the loader validates a *full historical* series, so
# series-level staleness (relative to real "now") is irrelevant — the engine
# enforces per-boundary causality itself.
_STALE_ALLOWANCE = 10**9


@dataclass(frozen=True)
class Dataset:
    """A validated, contiguous historical dataset keyed by (symbol_str, timeframe_str)."""

    name: str
    series: dict[tuple[str, str], list[Candle]]
    results: dict[tuple[str, str], ValidationResult]
    content_hash: str
    range_start: datetime | None
    range_end: datetime | None

    def candles(self, symbol: Symbol, timeframe: Timeframe) -> list[Candle]:
        return self.series.get((str(symbol), timeframe.value), [])

    def market_result(self, symbol: Symbol, timeframe: Timeframe) -> MarketDataResult:
        """The full validated series as a ``MarketDataResult`` for ``FeatureBuilder``.

        Feature causality is preserved by the engine's per-boundary indexing:
        P2 indicators are causal recursions, so ``build(full).snapshots[i]`` equals
        ``build(full[:i+1]).snapshots[-1]`` (proved by the no-look-ahead tests).
        """
        key = (str(symbol), timeframe.value)
        return MarketDataResult(candles=self.series.get(key, []), result=self.results[key])

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(sym for sym, _ in self.series))

    @property
    def timeframes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(tf for _, tf in self.series))


def _fname(symbol: Symbol, timeframe: Timeframe) -> str:
    return f"{symbol.base}-{symbol.quote}_{timeframe.value}.csv"


def _canonical_row(symbol: str, tf: str, c: Candle) -> str:
    def d(x: Decimal) -> str:
        return format(x, "f")

    return (
        f"{symbol}|{tf}|{c.open_time.isoformat()}|"
        f"{d(c.open)}|{d(c.high)}|{d(c.low)}|{d(c.close)}|{d(c.volume)}"
    )


def _hash_series(series: dict[tuple[str, str], list[Candle]]) -> str:
    h = hashlib.sha256()
    for (sym, tf) in sorted(series.keys()):
        for c in series[(sym, tf)]:
            h.update(_canonical_row(sym, tf, c).encode("utf-8"))
            h.update(b"\n")
    return h.hexdigest()


def _validate_series(
    raw: list[RawCandle], *, symbol: Symbol, timeframe: Timeframe
) -> tuple[list[Candle], ValidationResult]:
    if not raw:
        raise BacktestDataError(f"empty series for {symbol} {timeframe.value}")
    last_open = max((c.open_time for c in raw if c.open_time is not None), default=None)
    if last_open is None:
        raise BacktestDataError(f"no valid open_time for {symbol} {timeframe.value}")
    now = last_open + 2 * timeframe.delta  # ensure every candle is closed
    candles, result = validate_candles(
        raw,
        symbol=symbol,
        timeframe=timeframe,
        now=now,
        max_staleness_intervals=_STALE_ALLOWANCE,
    )
    if result.has_errors:
        codes = sorted({i.code.value for i in result.issues if i.severity.value == "error"})
        raise BacktestDataError(
            f"invalid dataset for {symbol} {timeframe.value}: {codes}"
        )
    if not result.quality.contiguous:
        raise BacktestDataError(
            f"gapped dataset for {symbol} {timeframe.value}: "
            f"{result.quality.missing_intervals} missing interval(s) — fix or exclude"
        )
    if not candles:
        raise BacktestDataError(f"no usable candles for {symbol} {timeframe.value}")
    return candles, result


def dataset_from_raw(
    name: str, raw_by_key: dict[tuple[Symbol, Timeframe], list[RawCandle]]
) -> Dataset:
    """Build a validated Dataset from in-memory raw candles (tests/CLI)."""
    series: dict[tuple[str, str], list[Candle]] = {}
    results: dict[tuple[str, str], ValidationResult] = {}
    starts: list[datetime] = []
    ends: list[datetime] = []
    for (symbol, timeframe), raw in raw_by_key.items():
        candles, result = _validate_series(raw, symbol=symbol, timeframe=timeframe)
        key = (str(symbol), timeframe.value)
        series[key] = candles
        results[key] = result
        starts.append(candles[0].open_time)
        ends.append(candles[-1].close_time)
    if not series:
        raise BacktestDataError(f"dataset {name!r} has no series")
    return Dataset(
        name=name,
        series=series,
        results=results,
        content_hash=_hash_series(series),
        range_start=min(starts) if starts else None,
        range_end=max(ends) if ends else None,
    )


def _read_csv(path: Path, *, symbol: Symbol, timeframe: Timeframe) -> list[RawCandle]:
    rows: list[RawCandle] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or tuple(reader.fieldnames) != _COLUMNS:
            raise BacktestDataError(
                f"{path.name}: expected columns {_COLUMNS}, got {reader.fieldnames}"
            )
        for line in reader:
            raw_ot = (line.get("open_time") or "").strip()
            try:
                open_time = datetime.fromisoformat(raw_ot) if raw_ot else None
            except ValueError:
                open_time = None  # let the validation gate flag it
            rows.append(
                RawCandle(
                    source=_SOURCE,
                    symbol=str(symbol),
                    timeframe=timeframe.value,
                    open_time=open_time,
                    open=(line.get("open") or "").strip() or None,
                    high=(line.get("high") or "").strip() or None,
                    low=(line.get("low") or "").strip() or None,
                    close=(line.get("close") or "").strip() or None,
                    volume=(line.get("volume") or "").strip() or None,
                )
            )
    return rows


def load_dataset(
    root: Path | str,
    name: str,
    *,
    symbols: list[Symbol],
    timeframes: list[Timeframe],
) -> Dataset:
    """Load and validate a CSV dataset from ``<root>/<name>/`` (offline)."""
    base = Path(root) / name
    if not base.is_dir():
        raise BacktestDataError(f"dataset directory not found: {base}")
    raw_by_key: dict[tuple[Symbol, Timeframe], list[RawCandle]] = {}
    for symbol in symbols:
        for timeframe in timeframes:
            path = base / _fname(symbol, timeframe)
            if not path.is_file():
                raise BacktestDataError(f"missing dataset file: {path}")
            raw_by_key[(symbol, timeframe)] = _read_csv(
                path, symbol=symbol, timeframe=timeframe
            )
    return dataset_from_raw(name, raw_by_key)


def write_dataset_csv(
    root: Path | str,
    name: str,
    raw_by_key: dict[tuple[Symbol, Timeframe], list[RawCandle]],
) -> Path:
    """Materialize raw candles to the CSV layout ``load_dataset`` expects.

    Used by the CLI and tests to build a deterministic offline snapshot. Money
    values are written as plain fixed-point strings.
    """
    base = Path(root) / name
    base.mkdir(parents=True, exist_ok=True)

    def fmt(x: object) -> str:
        if isinstance(x, Decimal):
            return format(x, "f")
        return "" if x is None else str(x)

    for (symbol, timeframe), raw in raw_by_key.items():
        path = base / _fname(symbol, timeframe)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(_COLUMNS)
            for c in raw:
                ot = c.open_time.isoformat() if isinstance(c.open_time, datetime) else ""
                writer.writerow(
                    [ot, fmt(c.open), fmt(c.high), fmt(c.low), fmt(c.close), fmt(c.volume)]
                )
    return base


__all__ = [
    "Dataset",
    "load_dataset",
    "dataset_from_raw",
    "write_dataset_csv",
]
