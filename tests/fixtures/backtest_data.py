"""Deterministic backtest fixtures (offline).

Programmatic OHLCV builders for the Phase 7 backtest tests. Generates a rising
series with periodic short pullbacks so the P4 candidate generator (EMA up-trend +
RSI pullback + ATR stop/target) can fire under a small, fast indicator config. No
network; ``BASE`` is aligned to both the 1h and 4h UTC epoch grids.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.indicators.config import IndicatorConfig
from app.market_data.models import RawCandle, Symbol, Timeframe
from app.risk.config import RiskConfig
from app.sizing.config import SizingConfig
from backtesting.dataset import Dataset, dataset_from_raw

BASE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)  # multiple of 3600 and 14400


def small_indicator_config() -> IndicatorConfig:
    """Fast-warming indicator config so tests produce signals with modest data."""
    return IndicatorConfig(ema_short=3, ema_long=8, rsi_period=3, atr_period=3)


def permissive_sizing_config() -> SizingConfig:
    """Sizing caps relaxed for the LOW-VOL synthetic fixture (logic unchanged).

    The synthetic series has small ATR%, so risk-budget sizing yields a large
    notional; relaxing the structural caps lets the reused sizer/RiskManager path
    execute so tests can exercise real trades. Only config *values* differ.
    """
    return SizingConfig(
        max_single_asset_exposure_pct=1.0,
        max_total_exposure_pct=1.0,
        correlated_exposure_cap_pct=1.0,
        max_simultaneous_positions=2,
    )


def permissive_risk_config() -> RiskConfig:
    """RiskManager exposure caps relaxed to match ``permissive_sizing_config``."""
    return RiskConfig(
        max_single_asset_exposure_pct=1.0,
        max_total_exposure_pct=1.0,
        correlated_exposure_cap_pct=1.0,
        max_simultaneous_positions=2,
    )


def tight_correlated_risk_config() -> RiskConfig:
    """A correlated-exposure cap tight enough that a SECOND BTC/ETH entry is blocked."""
    return RiskConfig(
        max_single_asset_exposure_pct=1.0,
        max_total_exposure_pct=1.0,
        correlated_exposure_cap_pct=0.50,  # one big position fits; two do not
        max_simultaneous_positions=2,
    )


def _closes(
    n: int, *, start: float, up: float, dip_every: int, dip_len: int, dip: float
) -> list[float]:
    val = start
    out: list[float] = []
    for i in range(n):
        if i > 0 and (i % dip_every) < dip_len:
            val -= dip  # short down-run → RSI pullback within the up-trend
        else:
            val += up
        out.append(round(val, 4))
    return out


def _raw_from_closes(
    closes: list[float], *, symbol: str, timeframe: Timeframe, base: datetime,
    open_gap: float = 0.0,
) -> list[RawCandle]:
    rows: list[RawCandle] = []
    prev = closes[0]
    for i, close in enumerate(closes):
        # open_gap != 0 makes bar-i+1 open differ from bar-i close so the two
        # entry-fill modes (next_open vs signal_close) are distinguishable.
        open_ = prev * (1.0 + open_gap)
        hi = max(open_, close) * 1.002
        lo = min(open_, close) * 0.998
        rows.append(
            RawCandle(
                source="backtest-fixture",
                symbol=symbol,
                timeframe=timeframe.value,
                open_time=base + i * timeframe.delta,
                open=f"{open_:.6f}",
                high=f"{hi:.6f}",
                low=f"{lo:.6f}",
                close=f"{close:.6f}",
                volume="10",
            )
        )
        prev = close
    return rows


def _aggregate_4h(closes_1h: list[float]) -> list[float]:
    """Aggregate 1h closes into 4h closes (last close of each 4-bar block)."""
    out: list[float] = []
    for i in range(0, len(closes_1h), 4):
        block = closes_1h[i : i + 4]
        if len(block) == 4:
            out.append(block[-1])
    return out


def build_raw(
    *,
    symbols: tuple[str, ...] = ("BTC/USDT", "ETH/USDT"),
    n_1h: int = 160,
    start: float = 100.0,
    up: float = 1.0,
    dip_every: int = 12,
    dip_len: int = 3,
    dip: float = 1.0,
    open_gap: float = 0.0,
    base: datetime = BASE,
) -> dict[tuple[Symbol, Timeframe], list[RawCandle]]:
    """Build a raw multi-symbol dataset (1h + aligned 4h) for the given symbols."""
    raw: dict[tuple[Symbol, Timeframe], list[RawCandle]] = {}
    for offset, sym_str in enumerate(symbols):
        closes_1h = _closes(
            n_1h, start=start + offset * 5.0, up=up,
            dip_every=dip_every, dip_len=dip_len, dip=dip,
        )
        closes_4h = _aggregate_4h(closes_1h)
        sym = Symbol.parse(sym_str)
        raw[(sym, Timeframe.H1)] = _raw_from_closes(
            closes_1h, symbol=sym_str, timeframe=Timeframe.H1, base=base, open_gap=open_gap
        )
        raw[(sym, Timeframe.H4)] = _raw_from_closes(
            closes_4h, symbol=sym_str, timeframe=Timeframe.H4, base=base, open_gap=open_gap
        )
    return raw


def build_dataset(name: str = "example", **kwargs: object) -> Dataset:
    return dataset_from_raw(name, build_raw(**kwargs))  # type: ignore[arg-type]


def build_crash_dataset(
    name: str = "crash",
    *,
    symbols: tuple[str, ...] = ("BTC/USDT",),
    up_bars: int = 120,
    crash_bars: int = 40,
    crash_step: float = 4.0,
    base: datetime = BASE,
) -> Dataset:
    """Rise (with pullbacks) then crash — forces stop-loss exits for open positions."""
    raw: dict[tuple[Symbol, Timeframe], list[RawCandle]] = {}
    for offset, sym_str in enumerate(symbols):
        up = _closes(up_bars, start=100.0 + offset * 5.0, up=1.0, dip_every=12, dip_len=3, dip=1.0)
        val = up[-1]
        crash = []
        for _ in range(crash_bars):
            val -= crash_step
            crash.append(round(val, 4))
        closes_1h = up + crash
        closes_4h = _aggregate_4h(closes_1h)
        sym = Symbol.parse(sym_str)
        raw[(sym, Timeframe.H1)] = _raw_from_closes(
            closes_1h, symbol=sym_str, timeframe=Timeframe.H1, base=base
        )
        raw[(sym, Timeframe.H4)] = _raw_from_closes(
            closes_4h, symbol=sym_str, timeframe=Timeframe.H4, base=base
        )
    return dataset_from_raw(name, raw)


def run_fixture_backtest(
    dataset: Dataset,
    settings,  # noqa: ANN001 (app.config.Settings)
    *,
    backtest_config=None,  # noqa: ANN001
    risk_config=None,  # noqa: ANN001
    symbols=None,  # noqa: ANN001
):  # noqa: ANN201
    """Run the backtest with the small/permissive test configs (logic unchanged)."""
    from backtesting.config import BacktestConfig
    from backtesting.engine import run_backtest

    return run_backtest(
        dataset,
        backtest_config=backtest_config or BacktestConfig(min_operational_trades=5),
        indicator_config=small_indicator_config(),
        strategy_config=settings.strategy_config(),
        cost_config=settings.cost_config(),
        sizing_config=permissive_sizing_config(),
        risk_config=risk_config or permissive_risk_config(),
        paper_config=settings.paper_config(),
        symbols=symbols,
    )


def trade_signatures(result) -> list[tuple]:  # noqa: ANN001
    return [
        (t.symbol, t.entry_time.isoformat(), str(t.entry_price), str(t.quantity),
         str(t.net_pnl), t.exit_reason)
        for t in result.trades
    ]


def approx_prices(values: list[str]) -> list[Decimal]:
    return [Decimal(v) for v in values]


__all__ = [
    "BASE",
    "small_indicator_config",
    "build_raw",
    "build_dataset",
    "approx_prices",
]
