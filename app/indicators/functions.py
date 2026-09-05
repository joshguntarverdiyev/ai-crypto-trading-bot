"""Pure, deterministic, causal indicator functions (Phase 2).

Operate on ``list[float]`` and return ``list[float | None]`` aligned by index.
Every value at index ``t`` uses only inputs at indices ``<= t`` (no look-ahead,
no centered windows). Not-yet-warm positions are ``None`` (never fabricated).

No third-party dependency (no pandas/numpy/pandas-ta) — full control over
warm-up and look-ahead semantics.
"""

from __future__ import annotations


def ema(values: list[float], period: int) -> list[float | None]:
    """Exponential moving average, SMA-seeded.

    First value at index ``period-1`` (= SMA of the first ``period`` inputs);
    thereafter ``EMA[i] = a*x[i] + (1-a)*EMA[i-1]`` with ``a = 2/(period+1)``.
    """
    if period <= 0:
        raise ValueError("ema period must be > 0")
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    alpha = 2.0 / (period + 1.0)
    prev = sum(values[:period]) / period  # SMA seed
    out[period - 1] = prev
    for i in range(period, n):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    # Deterministic flat/zero cases (all explicit — not implementation-dependent).
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:  # avg_gain > 0
        return 100.0
    if avg_gain == 0.0:  # avg_loss > 0
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def rsi_wilder(closes: list[float], period: int) -> list[float | None]:
    """Wilder's RSI. First value at index ``period`` (needs ``period+1`` closes)."""
    if period <= 0:
        raise ValueError("rsi period must be > 0")
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        if delta > 0:
            gains[i] = delta
        elif delta < 0:
            losses[i] = -delta
    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    out[period] = _rsi_from(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i] = _rsi_from(avg_gain, avg_loss)
    return out


def atr_wilder(
    highs: list[float], lows: list[float], closes: list[float], period: int
) -> list[float | None]:
    """Wilder's ATR. First value at index ``period`` (mean of TR[1..period])."""
    if period <= 0:
        raise ValueError("atr period must be > 0")
    n = len(closes)
    if not (len(highs) == len(lows) == n):
        raise ValueError("highs, lows, closes must have equal length")
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    tr = [0.0] * n
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = sum(tr[1 : period + 1]) / period
    out[period] = atr
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + tr[i]) / period
        out[i] = atr
    return out
