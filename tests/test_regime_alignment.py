"""governing_4h: source + symbol isolation and close_time selection (A–F)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.indicators.models import FeatureSnapshot
from app.market_data.models import Symbol, Timeframe
from app.regime.alignment import governing_4h

BTC = Symbol.parse("BTC/USDT")
ETH = Symbol.parse("ETH/USDT")
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _snap(close_time: datetime, *, source: str = "fixture", symbol: Symbol = BTC,
          tf: Timeframe = Timeframe.H4) -> FeatureSnapshot:
    return FeatureSnapshot(
        source=source, symbol=symbol, timeframe=tf,
        open_time=close_time - tf.delta, close_time=close_time,
        close=100.0, ema_short=100.0, ema_long=100.0, rsi=50.0, atr=1.0, atr_pct=0.01,
        warm=True, indicator_set_version="ind-v1",
    )


def _one_h(
    close_time: datetime, *, source: str = "fixture", symbol: Symbol = BTC
) -> FeatureSnapshot:
    return _snap(close_time, source=source, symbol=symbol, tf=Timeframe.H1)


def test_a_equal_close_time_is_governing() -> None:
    t1 = BASE + timedelta(hours=4)
    feat = _one_h(t1)
    gov = governing_4h(feat, [_snap(t1)])
    assert gov is not None and gov.close_time == t1


def test_b_different_source_not_eligible() -> None:
    t1 = BASE + timedelta(hours=4)
    feat = _one_h(t1, source="fixture")
    assert governing_4h(feat, [_snap(t1, source="other")]) is None


def test_c_different_symbol_not_eligible() -> None:
    t1 = BASE + timedelta(hours=4)
    feat = _one_h(t1, symbol=BTC)
    assert governing_4h(feat, [_snap(t1, symbol=ETH)]) is None


def test_d_multiple_eligible_picks_latest() -> None:
    t1 = BASE + timedelta(hours=8)
    feat = _one_h(t1)
    older = _snap(BASE + timedelta(hours=4))
    newer = _snap(BASE + timedelta(hours=8))
    gov = governing_4h(feat, [older, newer])
    assert gov is newer


def test_e_future_close_time_not_eligible() -> None:
    t1 = BASE + timedelta(hours=4)
    feat = _one_h(t1)
    assert governing_4h(feat, [_snap(BASE + timedelta(hours=8))]) is None


def test_f_no_match_returns_none() -> None:
    feat = _one_h(BASE + timedelta(hours=4))
    assert governing_4h(feat, []) is None
