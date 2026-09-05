"""RegimeClassifier: trend/volatility boundaries, confirmation, build-level stale."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.indicators.models import ComputeReason, FeatureResult, FeatureSnapshot
from app.market_data.models import Symbol, Timeframe
from app.regime.classifier import RegimeClassifier
from app.regime.config import RegimeConfig
from app.regime.models import TrendRegime, VolatilityRegime

BTC = Symbol.parse("BTC/USDT")
BASE = datetime(2026, 1, 1, tzinfo=UTC)
CFG = RegimeConfig(trend_band=0.01, vol_low_pct=0.005, vol_high_pct=0.02)


def _snap(
    *,
    tf: Timeframe = Timeframe.H1,
    open_time: datetime = BASE,
    close_time: datetime | None = None,
    ema_short: float | None = 100.0,
    ema_long: float | None = 100.0,
    atr_pct: float | None = 0.01,
    warm: bool = True,
    source: str = "fixture",
    symbol: Symbol = BTC,
) -> FeatureSnapshot:
    ct = close_time or (open_time + tf.delta)
    return FeatureSnapshot(
        source=source, symbol=symbol, timeframe=tf, open_time=open_time, close_time=ct,
        close=100.0,
        ema_short=ema_short if warm else None,
        ema_long=ema_long if warm else None,
        rsi=50.0 if warm else None,
        atr=1.0 if warm else None,
        atr_pct=atr_pct if warm else None,
        warm=warm, indicator_set_version="ind-v1",
    )


def _fr(snaps: list[FeatureSnapshot], *, stale: bool = False) -> FeatureResult:
    return FeatureResult(snaps, True, ComputeReason.OK, stale, "cfg")


def _classify_one(snap: FeatureSnapshot, four_h: FeatureResult | None = None):
    return RegimeClassifier(CFG).classify(_fr([snap]), four_h).snapshots[0]


@pytest.mark.parametrize(
    ("ema_short", "expected"),
    [
        (102.0, TrendRegime.UP),       # sep=0.02 > band
        (101.0, TrendRegime.RANGING),  # sep=0.01 == band -> RANGING (strict >)
        (100.5, TrendRegime.RANGING),  # sep=0.005 within band
        (99.0, TrendRegime.RANGING),   # sep=-0.01 == -band -> RANGING (strict <)
        (98.0, TrendRegime.DOWN),      # sep=-0.02 < -band
    ],
)
def test_trend_boundaries(ema_short: float, expected: TrendRegime) -> None:
    assert _classify_one(_snap(ema_short=ema_short, ema_long=100.0)).trend is expected


@pytest.mark.parametrize(
    ("atr_pct", "expected"),
    [
        (0.004, VolatilityRegime.LOW),
        (0.005, VolatilityRegime.NORMAL),   # == low -> NORMAL (strict <)
        (0.01, VolatilityRegime.NORMAL),
        (0.02, VolatilityRegime.NORMAL),    # == high -> NORMAL (strict >)
        (0.03, VolatilityRegime.HIGH),
    ],
)
def test_volatility_boundaries(atr_pct: float, expected: VolatilityRegime) -> None:
    assert _classify_one(_snap(atr_pct=atr_pct)).volatility is expected


def test_unknown_when_not_warm() -> None:
    rs = _classify_one(_snap(warm=False))
    assert rs.trend is TrendRegime.UNKNOWN
    assert rs.volatility is VolatilityRegime.UNKNOWN


def test_confirmation_when_4h_agrees() -> None:
    t1_close = BASE + Timeframe.H1.delta
    one_h = _snap(ema_short=102.0, ema_long=100.0)  # UP
    four = _snap(
        tf=Timeframe.H4, close_time=t1_close, ema_short=102.0, ema_long=100.0
    )  # UP, eligible
    rs = _classify_one(one_h, _fr([four]))
    assert rs.trend is TrendRegime.UP
    assert rs.trend_4h is TrendRegime.UP
    assert rs.confirmed is True
    assert rs.governing_4h_open_time == four.open_time


def test_not_confirmed_when_4h_disagrees_or_absent() -> None:
    one_h = _snap(ema_short=102.0, ema_long=100.0)  # UP
    four_down = _snap(tf=Timeframe.H4, close_time=BASE + Timeframe.H1.delta,
                      ema_short=98.0, ema_long=100.0)  # DOWN
    assert _classify_one(one_h, _fr([four_down])).confirmed is False
    assert _classify_one(one_h, None).confirmed is False  # no 4h


def test_g_matching_4h_not_warm_is_unknown() -> None:
    one_h = _snap(ema_short=102.0, ema_long=100.0)
    four_cold = _snap(tf=Timeframe.H4, close_time=BASE + Timeframe.H1.delta, warm=False)
    rs = _classify_one(one_h, _fr([four_cold]))
    assert rs.trend_4h is TrendRegime.UNKNOWN
    assert rs.confirmed is False
    assert rs.governing_4h_open_time == four_cold.open_time  # governing found, just not warm


@pytest.mark.parametrize(
    ("stale_1h", "stale_4h", "expected"),
    [(False, False, False), (True, False, True), (False, True, True), (True, True, True)],
)
def test_regime_result_stale_is_build_level(stale_1h: bool, stale_4h: bool, expected: bool) -> None:
    one = _fr([_snap()], stale=stale_1h)
    four = _fr([_snap(tf=Timeframe.H4, close_time=BASE + Timeframe.H1.delta)], stale=stale_4h)
    result = RegimeClassifier(CFG).classify(one, four)
    assert result.stale is expected
    # per-snapshot regime carries no stale field
    assert not hasattr(result.snapshots[0], "stale")


def test_source_symbol_from_1h_primary() -> None:
    one_h = _snap(source="fixture", symbol=BTC)
    rs = _classify_one(one_h)
    assert rs.source == "fixture"
    assert rs.symbol == BTC


def test_returns_regime_result_with_versions() -> None:
    result = RegimeClassifier(CFG).classify(_fr([_snap()]))
    assert result.regime_version == "reg-v1"
    assert result.config_version.startswith("reg-v1")
    assert len(result.snapshots) == 1
