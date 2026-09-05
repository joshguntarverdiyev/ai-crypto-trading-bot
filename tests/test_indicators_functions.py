"""Indicator functions: known-reference values, RSI guards, prefix-invariance."""

from __future__ import annotations

import math

import pytest

from app.indicators.functions import atr_wilder, ema, rsi_wilder


def test_ema_seed_and_recurrence_exact() -> None:
    # SMA(1,2,3)=2 at idx2; alpha=0.5 -> idx3=3, idx4=4
    assert ema([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_ema_none_before_warm_and_bad_period() -> None:
    assert ema([1.0, 2.0], 3) == [None, None]
    with pytest.raises(ValueError):
        ema([1.0], 0)


def test_rsi_flat_series_is_50() -> None:
    out = rsi_wilder([5.0, 5.0, 5.0, 5.0, 5.0], 2)
    assert out[:2] == [None, None]
    assert out[2:] == [50.0, 50.0, 50.0]


def test_rsi_all_gains_is_100() -> None:
    out = rsi_wilder([1.0, 2.0, 3.0, 4.0, 5.0], 2)
    assert all(v == 100.0 for v in out[2:])


def test_rsi_all_losses_is_0() -> None:
    out = rsi_wilder([5.0, 4.0, 3.0, 2.0, 1.0], 2)
    assert all(v == 0.0 for v in out[2:])


def test_atr_known_reference() -> None:
    highs = [10.0, 11.0, 12.0]
    lows = [8.0, 9.0, 10.0]
    closes = [9.0, 10.0, 11.0]
    out = atr_wilder(highs, lows, closes, 2)
    assert out == [None, None, 2.0]


def test_no_nan_or_inf_produced() -> None:
    closes = [float(x) for x in range(1, 30)]
    for series in (
        ema(closes, 5),
        rsi_wilder(closes, 5),
        atr_wilder([c + 1 for c in closes], [c - 1 for c in closes], closes, 5),
    ):
        assert all(v is None or math.isfinite(v) for v in series)


def test_determinism() -> None:
    closes = [1.0, 3.0, 2.0, 5.0, 4.0, 6.0, 7.0, 5.5]
    assert ema(closes, 3) == ema(closes, 3)
    assert rsi_wilder(closes, 3) == rsi_wilder(closes, 3)


@pytest.mark.parametrize("period", [2, 3, 5])
def test_prefix_invariance_no_lookahead(period: int) -> None:
    closes = [1.0, 3.0, 2.0, 5.0, 4.0, 6.0, 7.0, 5.5, 8.0, 7.0]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    full_ema = ema(closes, period)
    full_rsi = rsi_wilder(closes, period)
    full_atr = atr_wilder(highs, lows, closes, period)
    for k in range(1, len(closes) + 1):
        assert ema(closes[:k], period)[k - 1] == full_ema[k - 1]
        assert rsi_wilder(closes[:k], period)[k - 1] == full_rsi[k - 1]
        assert atr_wilder(highs[:k], lows[:k], closes[:k], period)[k - 1] == full_atr[k - 1]
