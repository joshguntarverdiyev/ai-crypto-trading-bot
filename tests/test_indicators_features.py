"""FeatureBuilder: gate (INVALID/GAP/EMPTY/NON_FINITE), warm, build-level stale."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from app.indicators.config import IndicatorConfig
from app.indicators.features import FeatureBuilder
from app.indicators.models import ComputeReason
from tests.fixtures.market_data import BASE, h1, market_result, now_after, valid_h1_series

CFG = IndicatorConfig(ema_short=2, ema_long=3, rsi_period=2, atr_period=2)


def test_valid_build_produces_warm_snapshots() -> None:
    mr = market_result(valid_h1_series(5), now=now_after(5))
    fr = FeatureBuilder(CFG).build(mr)
    assert fr.computed is True
    assert fr.reason is ComputeReason.OK
    assert len(fr.snapshots) == 5
    # warm once all indicators available (ema_long=3 -> idx2; rsi/atr period=2 -> idx2)
    assert fr.snapshots[0].warm is False
    assert fr.snapshots[-1].warm is True
    # snapshots carry no per-candle stale field (build-level only)
    assert not hasattr(fr.snapshots[0], "stale")


def test_invalid_series_no_features() -> None:
    mr = market_result([h1(0), h1(0)], now=now_after(3))  # duplicate -> INVALID
    fr = FeatureBuilder(CFG).build(mr)
    assert fr.computed is False
    assert fr.reason is ComputeReason.INVALID
    assert fr.snapshots == []


def test_gap_series_no_features() -> None:
    mr = market_result([h1(0), h1(2)], now=now_after(3))  # gap
    fr = FeatureBuilder(CFG).build(mr)
    assert fr.computed is False
    assert fr.reason is ComputeReason.GAP


def test_empty_series_no_features() -> None:
    mr = market_result([], now=now_after(3))
    fr = FeatureBuilder(CFG).build(mr)
    assert fr.computed is False
    assert fr.reason is ComputeReason.EMPTY


def test_stale_is_build_level_and_computes() -> None:
    mr = market_result(valid_h1_series(5), now=now_after(100))  # stale but contiguous
    fr = FeatureBuilder(CFG).build(mr)
    assert fr.computed is True
    assert fr.stale is True
    assert not hasattr(fr.snapshots[0], "stale")  # not per-snapshot


def test_non_finite_input_is_guarded() -> None:
    good = market_result(valid_h1_series(3), now=now_after(3))
    bad_candle = replace(good.candles[0], close=Decimal("Infinity"))
    mr = replace(good, candles=[bad_candle, *good.candles[1:]])
    fr = FeatureBuilder(CFG).build(mr)
    assert fr.computed is False
    assert fr.reason is ComputeReason.NON_FINITE


def test_feature_open_close_time_from_candle() -> None:
    mr = market_result(valid_h1_series(3), now=now_after(3))
    fr = FeatureBuilder(CFG).build(mr)
    snap = fr.snapshots[0]
    assert snap.open_time == BASE
    assert snap.close_time == BASE + timedelta(hours=1)
