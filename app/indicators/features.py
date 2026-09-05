"""FeatureBuilder — consumes Phase 1 MarketDataResult → FeatureResult (Phase 2).

Gate (fail-safe): compute only when the series is not INVALID, is contiguous,
and non-empty. Gaps/INVALID/EMPTY → no features (reason flagged). Stale-but-
contiguous → compute, with build-level ``stale`` propagated.

Numerical policy: money stays Decimal (Phase 1); indicators use float. The
Decimal→float conversion happens ONCE here, at the input boundary, and every
converted value must be finite (non-finite → ComputeReason.NON_FINITE). No NaN
or infinity may appear in a FeatureSnapshot.
"""

from __future__ import annotations

import math

from app.indicators.config import INDICATOR_SET_VERSION, IndicatorConfig
from app.indicators.functions import atr_wilder, ema, rsi_wilder
from app.indicators.models import ComputeReason, FeatureResult, FeatureSnapshot
from app.market_data.service import MarketDataResult
from app.market_data.validation import SeriesUsability


class FeatureBuilder:
    def __init__(self, config: IndicatorConfig | None = None) -> None:
        self._cfg = config or IndicatorConfig()

    def build(self, market_data: MarketDataResult) -> FeatureResult:
        result = market_data.result
        candles = market_data.candles
        cfgv = self._cfg.version_tag
        stale = result.quality.stale  # SERIES/BUILD-LEVEL

        # --- gate (fail-safe) ---
        if result.usability is SeriesUsability.INVALID:
            return FeatureResult([], False, ComputeReason.INVALID, stale, cfgv)
        if not candles:
            return FeatureResult([], False, ComputeReason.EMPTY, stale, cfgv)
        if not result.quality.contiguous:
            return FeatureResult([], False, ComputeReason.GAP, stale, cfgv)

        # --- Decimal -> float boundary + finite validation (once) ---
        closes: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        for c in candles:
            fc, fh, fl = float(c.close), float(c.high), float(c.low)
            if not (math.isfinite(fc) and math.isfinite(fh) and math.isfinite(fl)):
                return FeatureResult([], False, ComputeReason.NON_FINITE, stale, cfgv)
            closes.append(fc)
            highs.append(fh)
            lows.append(fl)

        ema_s = ema(closes, self._cfg.ema_short)
        ema_l = ema(closes, self._cfg.ema_long)
        rsi = rsi_wilder(closes, self._cfg.rsi_period)
        atr = atr_wilder(highs, lows, closes, self._cfg.atr_period)

        timeframe = candles[0].timeframe
        snapshots: list[FeatureSnapshot] = []
        for i, c in enumerate(candles):
            a = atr[i]
            atr_pct = (a / closes[i]) if (a is not None and closes[i] != 0.0) else None
            values = (ema_s[i], ema_l[i], rsi[i], a, atr_pct)
            for v in values:
                if v is not None and not math.isfinite(v):
                    return FeatureResult([], False, ComputeReason.NON_FINITE, stale, cfgv)
            warm = all(v is not None for v in values)
            snapshots.append(
                FeatureSnapshot(
                    source=c.source,
                    symbol=c.symbol,
                    timeframe=timeframe,
                    open_time=c.open_time,
                    close_time=c.close_time,
                    close=closes[i],
                    ema_short=ema_s[i],
                    ema_long=ema_l[i],
                    rsi=rsi[i],
                    atr=a,
                    atr_pct=atr_pct,
                    warm=warm,
                    indicator_set_version=INDICATOR_SET_VERSION,
                )
            )
        return FeatureResult(snapshots, True, ComputeReason.OK, stale, cfgv)
