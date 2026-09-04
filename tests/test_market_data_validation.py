"""Validation contract: per-issue codes, usability, accounting, staleness, ticker."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.market_data.models import Symbol, Timeframe
from app.market_data.validation import (
    IssueCode,
    SeriesUsability,
    validate_candles,
    validate_ticker,
)
from tests.fixtures.market_data import (
    BASE,
    h1,
    now_after,
    raw_candle,
    raw_ticker,
    valid_h1_series,
)

BTC = Symbol.parse("BTC/USDT")
H1 = Timeframe.H1
FAR = now_after(1000)  # everything closed


def _codes(raw: list, **kw: object) -> set[IssueCode]:
    _, result = validate_candles(raw, symbol=BTC, timeframe=H1, now=FAR, **kw)  # type: ignore[arg-type]
    return {i.code for i in result.issues}


def test_valid_series_is_usable() -> None:
    raw = valid_h1_series(5)
    candles, result = validate_candles(raw, symbol=BTC, timeframe=H1, now=now_after(5))
    assert result.usability is SeriesUsability.USABLE
    assert result.usable is True
    assert len(candles) == 5
    assert result.quality.accepted_count == 5
    assert result.quality.rejected_count == 0


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ([raw_candle(None)], IssueCode.MISSING_FIELD),
        ([h1(0, o=None)], IssueCode.MISSING_FIELD),
        ([h1(0, o=Decimal("NaN"))], IssueCode.NON_FINITE),
        ([h1(0, o=Decimal("Infinity"))], IssueCode.NON_FINITE),
        ([h1(0, o="0")], IssueCode.NON_POSITIVE_PRICE),
        ([h1(0, o="-5")], IssueCode.NON_POSITIVE_PRICE),
        ([h1(0, v="-1")], IssueCode.NEGATIVE_VOLUME),
        ([h1(0, h="50")], IssueCode.OHLC_RELATION),  # high < open
        ([raw_candle(BASE.replace(tzinfo=None))], IssueCode.NAIVE_TIMESTAMP),
        ([raw_candle(BASE + timedelta(minutes=30))], IssueCode.MISALIGNED_TIMESTAMP),
        ([h1(0, symbol="ETH/USDT")], IssueCode.SYMBOL_MISMATCH),
        ([h1(0, timeframe="4h")], IssueCode.TIMEFRAME_MISMATCH),
    ],
)
def test_per_candle_issue_codes(raw: list, code: IssueCode) -> None:
    assert code in _codes(raw)


def test_future_timestamp() -> None:
    raw = [h1(50)]  # open far in future relative to a small now
    _, result = validate_candles(raw, symbol=BTC, timeframe=H1, now=now_after(1))
    assert IssueCode.FUTURE_TIMESTAMP in {i.code for i in result.issues}
    assert result.usability is SeriesUsability.INVALID


def test_duplicate_and_out_of_order_make_invalid() -> None:
    dup = [h1(0), h1(1), h1(1)]
    _, r1 = validate_candles(dup, symbol=BTC, timeframe=H1, now=FAR)
    assert r1.quality.duplicate_count == 1
    assert r1.usability is SeriesUsability.INVALID

    ooo = [h1(0), h1(2), h1(1)]
    _, r2 = validate_candles(ooo, symbol=BTC, timeframe=H1, now=FAR)
    assert r2.quality.out_of_order_count == 1
    assert r2.usability is SeriesUsability.INVALID


def test_duplicate_and_out_of_order_can_overlap() -> None:
    # third candle @1 is both a duplicate (kept earlier) and out of order (< last kept @2)
    raw = [h1(1), h1(2), h1(1)]
    _, r = validate_candles(raw, symbol=BTC, timeframe=H1, now=FAR)
    assert r.quality.duplicate_count == 1
    assert r.quality.out_of_order_count == 1
    assert r.quality.rejected_count == 1  # counted once in rejected


def test_gap_makes_incomplete_not_invalid() -> None:
    raw = [h1(0), h1(2)]  # missing hour 1
    candles, r = validate_candles(raw, symbol=BTC, timeframe=H1, now=now_after(3))
    assert r.quality.gap_count == 1
    assert r.quality.missing_intervals == 1
    assert r.quality.contiguous is False
    assert r.usability is SeriesUsability.INCOMPLETE
    assert len(candles) == 2  # both valid candles still returned


def test_empty_series() -> None:
    candles, r = validate_candles([], symbol=BTC, timeframe=H1, now=FAR)
    assert candles == []
    assert r.usability is SeriesUsability.EMPTY
    assert IssueCode.EMPTY in {i.code for i in r.issues}


def test_incomplete_at_end_excluded() -> None:
    raw = valid_h1_series(5)  # candles 0..4
    now = BASE + timedelta(hours=4, minutes=30)  # candle 4 not yet closed
    candles, r = validate_candles(raw, symbol=BTC, timeframe=H1, now=now)
    assert len(candles) == 4
    assert r.quality.incomplete_count == 1
    assert r.usability is SeriesUsability.USABLE


def test_incomplete_in_middle_of_list_excluded_not_out_of_order() -> None:
    # list order places the incomplete candle (@3) in the middle
    raw = [h1(0), h1(3), h1(1), h1(2)]
    now = BASE + timedelta(hours=3, minutes=30)  # candle @3 open<=now, close>now
    candles, r = validate_candles(raw, symbol=BTC, timeframe=H1, now=now)
    assert [c.open_time for c in candles] == [BASE + timedelta(hours=i) for i in (0, 1, 2)]
    assert r.quality.incomplete_count == 1
    assert r.quality.out_of_order_count == 0  # incomplete removed before series checks
    assert r.usable is True


def test_incomplete_only_candle_is_empty() -> None:
    raw = [h1(0)]
    now = BASE + timedelta(minutes=30)  # not closed
    candles, r = validate_candles(raw, symbol=BTC, timeframe=H1, now=now)
    assert candles == []
    assert r.quality.incomplete_count == 1
    assert r.usability is SeriesUsability.EMPTY


def test_malformed_plus_incomplete_overlap() -> None:
    bad = raw_candle(BASE + timedelta(hours=3), o="-5")  # non-positive AND (with now) incomplete
    raw = [h1(0), bad]
    now = BASE + timedelta(hours=3, minutes=30)
    _, r = validate_candles(raw, symbol=BTC, timeframe=H1, now=now)
    assert r.quality.malformed_count == 1
    assert r.quality.incomplete_count == 1
    assert r.quality.rejected_count == 1  # same candle, counted once


def test_accounting_invariant_holds() -> None:
    raw = [h1(0), h1(0), h1(2), raw_candle(None)]  # dup, gap, missing-field
    candles, r = validate_candles(raw, symbol=BTC, timeframe=H1, now=FAR)
    q = r.quality
    assert q.accepted_count + q.rejected_count == q.input_count
    assert q.accepted_count == len(candles)


@pytest.mark.parametrize(
    ("now_hours", "expect_stale"),
    [(5, False), (6, False), (7, True)],  # last=@4: T=@4 fresh, @5 tolerated, @6 stale
)
def test_staleness_boundaries(now_hours: int, expect_stale: bool) -> None:
    raw = valid_h1_series(5)  # candles 0..4, last open @4
    _, r = validate_candles(raw, symbol=BTC, timeframe=H1, now=now_after(now_hours))
    assert r.quality.stale is expect_stale


# --- ticker ---


def test_ticker_valid() -> None:
    t, r = validate_ticker(raw_ticker(), symbol=BTC, now=BASE + timedelta(seconds=5))
    assert t is not None
    assert r.usable is True


def test_ticker_bid_ask_crossed() -> None:
    t, r = validate_ticker(
        raw_ticker(bid="101", ask="100"), symbol=BTC, now=BASE + timedelta(seconds=5)
    )
    assert t is None
    assert IssueCode.BID_ASK_CROSSED in {i.code for i in r.issues}


def test_ticker_stale_uses_config_seconds() -> None:
    t, r = validate_ticker(
        raw_ticker(),
        symbol=BTC,
        now=BASE + timedelta(seconds=120),
        ticker_staleness_seconds=30,
    )
    assert t is not None  # still constructs
    assert r.quality.stale is True
    assert r.usability is SeriesUsability.INCOMPLETE


def test_ticker_naive_rejected() -> None:
    t, r = validate_ticker(
        raw_ticker(timestamp=BASE.replace(tzinfo=None)), symbol=BTC, now=BASE
    )
    assert t is None
    assert IssueCode.NAIVE_TIMESTAMP in {i.code for i in r.issues}
