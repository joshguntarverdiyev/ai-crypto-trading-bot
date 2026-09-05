"""RegimeClassifier — deterministic descriptive regime (Phase 2).

Pure function of the current feature snapshot (stateless). Trend from EMA50/200
separation vs the neutral band; volatility from ATR%. 1h is primary; the
governing 4h feature (same source+symbol, causal) provides confirmation.
``RegimeResult.stale`` is BUILD-level, propagated from the 1h/4h FeatureResults.
Not a trading signal.
"""

from __future__ import annotations

from app.indicators.models import FeatureResult
from app.regime.alignment import governing_4h
from app.regime.config import REGIME_VERSION, RegimeConfig
from app.regime.models import (
    RegimeResult,
    RegimeSnapshot,
    TrendRegime,
    VolatilityRegime,
)


class RegimeClassifier:
    def __init__(self, config: RegimeConfig | None = None) -> None:
        self._cfg = config or RegimeConfig()

    def _trend(self, ema_short: float | None, ema_long: float | None) -> TrendRegime:
        if ema_short is None or ema_long is None or ema_long == 0.0:
            return TrendRegime.UNKNOWN
        sep = (ema_short - ema_long) / ema_long
        if sep > self._cfg.trend_band:
            return TrendRegime.UP
        if sep < -self._cfg.trend_band:
            return TrendRegime.DOWN
        return TrendRegime.RANGING

    def _volatility(self, atr_pct: float | None) -> VolatilityRegime:
        if atr_pct is None:
            return VolatilityRegime.UNKNOWN
        if atr_pct < self._cfg.vol_low_pct:
            return VolatilityRegime.LOW
        if atr_pct > self._cfg.vol_high_pct:
            return VolatilityRegime.HIGH
        return VolatilityRegime.NORMAL

    def classify(
        self, feature_1h: FeatureResult, feature_4h: FeatureResult | None = None
    ) -> RegimeResult:
        snapshots_4h = feature_4h.snapshots if feature_4h is not None else []
        out: list[RegimeSnapshot] = []
        for s in feature_1h.snapshots:
            trend = self._trend(s.ema_short, s.ema_long)
            volatility = self._volatility(s.atr_pct)
            governing = governing_4h(s, snapshots_4h) if snapshots_4h else None
            if governing is not None:
                trend_4h = self._trend(governing.ema_short, governing.ema_long)
                governing_open = governing.open_time
            else:
                trend_4h = TrendRegime.UNKNOWN
                governing_open = None
            confirmed = (
                trend is not TrendRegime.UNKNOWN
                and trend_4h is not TrendRegime.UNKNOWN
                and trend == trend_4h
            )
            out.append(
                RegimeSnapshot(
                    open_time=s.open_time,
                    symbol=s.symbol,  # from the 1h primary snapshot
                    source=s.source,  # from the 1h primary snapshot
                    trend=trend,
                    volatility=volatility,
                    trend_4h=trend_4h,
                    confirmed=confirmed,
                    governing_4h_open_time=governing_open,
                    regime_version=REGIME_VERSION,
                )
            )
        stale = feature_1h.stale or (feature_4h is not None and feature_4h.stale)
        return RegimeResult(
            snapshots=out,
            stale=stale,
            config_version=self._cfg.version_tag,
            regime_version=REGIME_VERSION,
        )
