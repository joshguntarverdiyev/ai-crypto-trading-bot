"""Deterministic market-data validation (Phase 1).

Machine-consumable results only — downstream code reads structured fields
(``result.usable``, ``result.usability``, ``result.quality``, ``issue.code``),
never log strings.

Data-quality problems produce a :class:`ValidationResult` (never an exception).
Only infrastructure/programming problems raise (see app.exceptions).

Accounting invariant (authoritative):
    accepted_count + rejected_count == input_count
    accepted_count == len(returned candles)
Each rejected input candle contributes exactly once to ``rejected_count``.
Per-reason counters are occurrence counters and may overlap:
  * per-candle scope (all input): ``malformed_count``, ``incomplete_count``
  * candidate scope (structurally-valid AND closed survivors):
    ``duplicate_count``, ``out_of_order_count``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from app.market_data.models import (
    Candle,
    RawCandle,
    RawTicker,
    Symbol,
    Ticker,
    Timeframe,
    utc_epoch_aligned,
)


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class IssueCode(StrEnum):
    MISSING_FIELD = "missing_field"
    NON_FINITE = "non_finite"
    NON_POSITIVE_PRICE = "non_positive_price"
    NEGATIVE_VOLUME = "negative_volume"
    OHLC_RELATION = "ohlc_relation"
    NAIVE_TIMESTAMP = "naive_timestamp"
    FUTURE_TIMESTAMP = "future_timestamp"
    MISALIGNED_TIMESTAMP = "misaligned_timestamp"
    SYMBOL_MISMATCH = "symbol_mismatch"
    TIMEFRAME_MISMATCH = "timeframe_mismatch"
    OUT_OF_ORDER = "out_of_order"
    DUPLICATE = "duplicate"
    GAP = "gap"
    STALE = "stale"
    EMPTY = "empty"
    BID_ASK_CROSSED = "bid_ask_crossed"


class SeriesUsability(StrEnum):
    USABLE = "usable"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"
    EMPTY = "empty"


@dataclass(frozen=True)
class ValidationIssue:
    code: IssueCode
    severity: Severity
    message: str
    context: dict[str, object] = field(default_factory=dict)
    open_time: datetime | None = None


@dataclass(frozen=True)
class DataQuality:
    input_count: int
    accepted_count: int
    rejected_count: int
    malformed_count: int
    incomplete_count: int
    duplicate_count: int
    out_of_order_count: int
    gap_count: int
    missing_intervals: int
    stale: bool
    contiguous: bool
    first_open_time: datetime | None
    last_open_time: datetime | None


@dataclass(frozen=True)
class ValidationResult:
    usability: SeriesUsability
    issues: list[ValidationIssue]
    quality: DataQuality

    @property
    def usable(self) -> bool:
        return self.usability is SeriesUsability.USABLE

    @property
    def has_errors(self) -> bool:
        return any(i.severity is Severity.ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity is Severity.WARNING for i in self.issues)


# --- internal helpers ---


def _parse_decimal(value: Decimal | str | int | None) -> Decimal | None:
    """Best-effort parse to Decimal; None if missing/unparseable/float."""
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _is_finite(d: Decimal | None) -> bool:
    return d is not None and d.is_finite()


@dataclass
class _CandidateEval:
    raw: RawCandle
    structurally_valid: bool
    incomplete: bool
    open_utc: datetime | None
    prices: tuple[Decimal, Decimal, Decimal, Decimal] | None  # o,h,l,c
    volume: Decimal | None


def _validate_one(
    raw: RawCandle,
    *,
    symbol: Symbol,
    timeframe: Timeframe,
    now: datetime,
    future_tolerance_seconds: int,
    issues: list[ValidationIssue],
) -> _CandidateEval:
    """Per-candle structural validation. Appends ERROR issues; returns evaluation."""
    ok = True

    def err(code: IssueCode, msg: str) -> None:
        nonlocal ok
        ok = False
        issues.append(
            ValidationIssue(code, Severity.ERROR, msg, {"symbol": str(symbol)}, ot_ctx)
        )

    ot_ctx = raw.open_time

    # identity consistency
    if raw.symbol != str(symbol):
        err(IssueCode.SYMBOL_MISMATCH, f"symbol {raw.symbol!r} != {symbol!s}")
    if raw.timeframe != timeframe.value:
        err(IssueCode.TIMEFRAME_MISMATCH, f"timeframe {raw.timeframe!r} != {timeframe.value}")

    # timestamp
    open_utc: datetime | None = None
    if raw.open_time is None:
        err(IssueCode.MISSING_FIELD, "open_time missing")
    elif raw.open_time.tzinfo is None:
        err(IssueCode.NAIVE_TIMESTAMP, "open_time is timezone-naive")
    else:
        open_utc = raw.open_time.astimezone(UTC)
        if not utc_epoch_aligned(open_utc, timeframe):
            err(IssueCode.MISALIGNED_TIMESTAMP, "open_time not aligned to timeframe boundary")
        if open_utc > now + timedelta(seconds=future_tolerance_seconds):
            err(IssueCode.FUTURE_TIMESTAMP, "open_time is in the future")

    # numeric fields
    o = _parse_decimal(raw.open)
    h = _parse_decimal(raw.high)
    low = _parse_decimal(raw.low)
    c = _parse_decimal(raw.close)
    v = _parse_decimal(raw.volume)
    prices_raw = (o, h, low, c)

    if any(x is None for x in (o, h, low, c, v)):
        err(IssueCode.MISSING_FIELD, "missing/unparseable OHLCV field")
    if not all(_is_finite(x) for x in (o, h, low, c, v)):
        err(IssueCode.NON_FINITE, "non-finite OHLCV value")
    elif any(x is not None and x <= 0 for x in prices_raw):  # finite here
        err(IssueCode.NON_POSITIVE_PRICE, "non-positive price")
    if v is not None and v.is_finite() and v < 0:
        err(IssueCode.NEGATIVE_VOLUME, "negative volume")

    prices: tuple[Decimal, Decimal, Decimal, Decimal] | None = None
    if all(_is_finite(x) for x in prices_raw):
        assert o is not None and h is not None and low is not None and c is not None
        prices = (o, h, low, c)
        if not (h >= max(o, c, low) and low <= min(o, c, h) and h >= low):
            err(IssueCode.OHLC_RELATION, "OHLC relationship violated")

    incomplete = False
    if open_utc is not None:
        close_time = open_utc + timeframe.delta
        incomplete = not (close_time <= now)

    return _CandidateEval(
        raw=raw,
        structurally_valid=ok,
        incomplete=incomplete,
        open_utc=open_utc,
        prices=prices,
        volume=v if (v is not None and v.is_finite()) else None,
    )


def _empty_quality(now_note: bool = True) -> DataQuality:
    return DataQuality(
        input_count=0,
        accepted_count=0,
        rejected_count=0,
        malformed_count=0,
        incomplete_count=0,
        duplicate_count=0,
        out_of_order_count=0,
        gap_count=0,
        missing_intervals=0,
        stale=now_note,
        contiguous=True,
        first_open_time=None,
        last_open_time=None,
    )


def validate_candles(
    raw_candles: list[RawCandle],
    *,
    symbol: Symbol,
    timeframe: Timeframe,
    now: datetime,
    max_staleness_intervals: int = 1,
    future_tolerance_seconds: int = 2,
) -> tuple[list[Candle], ValidationResult]:
    """Validate a raw candle series → (accepted canonical candles, result).

    Pipeline (deterministic): per-candle structural validation on ALL input →
    per-candle ``is_closed(now)`` → candidate acceptance (valid AND closed) →
    series duplicate/order checks on candidates → gaps/staleness → usability.
    """
    issues: list[ValidationIssue] = []
    input_count = len(raw_candles)

    if input_count == 0:
        q = _empty_quality()
        issues.append(ValidationIssue(IssueCode.EMPTY, Severity.WARNING, "no candles", {}))
        return [], ValidationResult(SeriesUsability.EMPTY, issues, q)

    # Scope (i): per-candle validation over all input.
    evals: list[_CandidateEval] = []
    malformed_count = 0
    incomplete_count = 0
    for rc in raw_candles:
        ev = _validate_one(
            rc,
            symbol=symbol,
            timeframe=timeframe,
            now=now,
            future_tolerance_seconds=future_tolerance_seconds,
            issues=issues,
        )
        evals.append(ev)
        if not ev.structurally_valid:
            malformed_count += 1
        if ev.incomplete:
            incomplete_count += 1

    # Candidate set: structurally valid AND closed.
    candidates = [ev for ev in evals if ev.structurally_valid and not ev.incomplete]

    # Scope (ii): duplicate / out-of-order on candidates (in adapter order).
    accepted: list[Candle] = []
    seen: set[datetime] = set()
    last_kept: datetime | None = None
    duplicate_count = 0
    out_of_order_count = 0
    for ev in candidates:
        assert ev.open_utc is not None and ev.prices is not None and ev.volume is not None
        ot = ev.open_utc
        is_dup = ot in seen
        is_ooo = last_kept is not None and ot < last_kept
        if is_dup:
            duplicate_count += 1
            issues.append(
                ValidationIssue(IssueCode.DUPLICATE, Severity.ERROR, "duplicate open_time", {}, ot)
            )
        if is_ooo:
            out_of_order_count += 1
            issues.append(
                ValidationIssue(
                    IssueCode.OUT_OF_ORDER, Severity.ERROR, "out-of-order open_time", {}, ot
                )
            )
        if is_dup or is_ooo:
            continue
        o, h, low, c = ev.prices
        accepted.append(
            Candle(
                source=ev.raw.source,
                symbol=symbol,
                timeframe=timeframe,
                open_time=ot,
                open=o,
                high=h,
                low=low,
                close=c,
                volume=ev.volume,
            )
        )
        seen.add(ot)
        last_kept = ot

    accepted_count = len(accepted)
    rejected_count = input_count - accepted_count

    # Series metrics on accepted (strictly ascending by construction).
    gap_count = 0
    missing_intervals = 0
    for prev, nxt in zip(accepted, accepted[1:], strict=False):
        step = int((nxt.open_time - prev.open_time).total_seconds()) // timeframe.seconds
        if step > 1:
            gap_count += 1
            missing = step - 1
            missing_intervals += missing
            issues.append(
                ValidationIssue(
                    IssueCode.GAP,
                    Severity.WARNING,
                    f"{missing} missing interval(s)",
                    {"missing": missing},
                    nxt.open_time,
                )
            )
    contiguous = gap_count == 0

    # Staleness vs latest expected completed candle.
    stale = _evaluate_staleness(
        accepted, timeframe=timeframe, now=now, max_staleness_intervals=max_staleness_intervals
    )
    if accepted and stale:
        issues.append(ValidationIssue(IssueCode.STALE, Severity.WARNING, "series is stale", {}))

    quality = DataQuality(
        input_count=input_count,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        malformed_count=malformed_count,
        incomplete_count=incomplete_count,
        duplicate_count=duplicate_count,
        out_of_order_count=out_of_order_count,
        gap_count=gap_count,
        missing_intervals=missing_intervals,
        stale=stale,
        contiguous=contiguous,
        first_open_time=accepted[0].open_time if accepted else None,
        last_open_time=accepted[-1].open_time if accepted else None,
    )

    has_error = any(i.severity is Severity.ERROR for i in issues)
    if has_error:
        usability = SeriesUsability.INVALID
    elif accepted_count == 0:
        usability = SeriesUsability.EMPTY
        issues.append(ValidationIssue(IssueCode.EMPTY, Severity.WARNING, "no usable candles", {}))
    elif (not contiguous) or stale:
        usability = SeriesUsability.INCOMPLETE
    else:
        usability = SeriesUsability.USABLE

    return accepted, ValidationResult(usability, issues, quality)


def _evaluate_staleness(
    accepted: list[Candle],
    *,
    timeframe: Timeframe,
    now: datetime,
    max_staleness_intervals: int,
) -> bool:
    if not accepted:
        return True  # empty series is not fresh
    secs = timeframe.seconds
    now_epoch = int(now.astimezone(UTC).timestamp())
    cur_open = (now_epoch // secs) * secs
    expected_last_closed_open = cur_open - secs
    last_epoch = int(accepted[-1].open_time.timestamp())
    lag_intervals = (expected_last_closed_open - last_epoch) // secs
    return lag_intervals > max_staleness_intervals


def validate_ticker(
    raw: RawTicker,
    *,
    symbol: Symbol,
    now: datetime,
    future_tolerance_seconds: int = 2,
    ticker_staleness_seconds: int = 30,
) -> tuple[Ticker | None, ValidationResult]:
    """Validate a raw ticker (transient — not persisted). Deterministic/offline."""
    issues: list[ValidationIssue] = []

    def err(code: IssueCode, msg: str) -> None:
        issues.append(ValidationIssue(code, Severity.ERROR, msg, {"symbol": str(symbol)}, None))

    if raw.symbol != str(symbol):
        err(IssueCode.SYMBOL_MISMATCH, f"symbol {raw.symbol!r} != {symbol!s}")

    ts_utc: datetime | None = None
    stale = False
    if raw.timestamp is None:
        err(IssueCode.MISSING_FIELD, "timestamp missing")
    elif raw.timestamp.tzinfo is None:
        err(IssueCode.NAIVE_TIMESTAMP, "timestamp is timezone-naive")
    else:
        ts_utc = raw.timestamp.astimezone(UTC)
        if ts_utc > now + timedelta(seconds=future_tolerance_seconds):
            err(IssueCode.FUTURE_TIMESTAMP, "timestamp is in the future")
        if (now - ts_utc).total_seconds() > ticker_staleness_seconds:
            stale = True
            issues.append(ValidationIssue(IssueCode.STALE, Severity.WARNING, "ticker is stale", {}))

    bid = _parse_decimal(raw.bid)
    ask = _parse_decimal(raw.ask)
    last = _parse_decimal(raw.last)
    if any(x is None for x in (bid, ask, last)):
        err(IssueCode.MISSING_FIELD, "missing/unparseable price")
    if not all(_is_finite(x) for x in (bid, ask, last)):
        err(IssueCode.NON_FINITE, "non-finite price")
    elif any(x is not None and x <= 0 for x in (bid, ask, last)):
        err(IssueCode.NON_POSITIVE_PRICE, "non-positive price")
    elif bid is not None and ask is not None and bid > ask:
        err(IssueCode.BID_ASK_CROSSED, "bid > ask")

    has_error = any(i.severity is Severity.ERROR for i in issues)
    ticker: Ticker | None = None
    prices_ok = ts_utc is not None and bid is not None and ask is not None and last is not None
    if not has_error and prices_ok:
        assert ts_utc is not None and bid is not None and ask is not None and last is not None
        ticker = Ticker(
            source=raw.source, symbol=symbol, timestamp=ts_utc, bid=bid, ask=ask, last=last
        )

    accepted = 1 if ticker is not None else 0
    quality = DataQuality(
        input_count=1,
        accepted_count=accepted,
        rejected_count=1 - accepted,
        malformed_count=0 if ticker is not None else 1,
        incomplete_count=0,
        duplicate_count=0,
        out_of_order_count=0,
        gap_count=0,
        missing_intervals=0,
        stale=stale,
        contiguous=True,
        first_open_time=ts_utc,
        last_open_time=ts_utc,
    )
    if has_error:
        usability = SeriesUsability.INVALID
    elif stale:
        usability = SeriesUsability.INCOMPLETE
    else:
        usability = SeriesUsability.USABLE
    return ticker, ValidationResult(usability, issues, quality)
