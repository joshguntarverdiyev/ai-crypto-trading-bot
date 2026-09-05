# Phase 2 — Indicators + Market Regime

Deterministic technical indicators/features and **descriptive** market-regime
classification, computed from Phase 1 candle series. No strategy, entry/exit
signals, sizing, cost, news, AI, risk, execution, exchange/network, or new
dependencies. Fully offline and deterministic.

Authoritative design: the Master Plan (`/Users/josh/.claude/plans/curious-stargazing-chipmunk.md`).

## Modules

* `app/indicators/functions.py` — pure causal `ema`, `rsi_wilder`, `atr_wilder`
  (`list[float] → list[float | None]`); SMA-seeded EMA; Wilder RSI/ATR.
* `app/indicators/config.py` — `IndicatorConfig` (EMA50/200, RSI14, ATR14;
  invariant `0 < ema_short < ema_long`) + `INDICATOR_SET_VERSION`.
* `app/indicators/models.py` — `FeatureSnapshot`, `FeatureResult`, `ComputeReason`.
* `app/indicators/features.py` — `FeatureBuilder`: consumes `MarketDataResult`,
  applies the gate, converts Decimal→float once with finite validation, emits
  per-candle features.
* `app/regime/{config,models,alignment,classifier}.py` — `RegimeConfig`,
  `TrendRegime`/`VolatilityRegime`, `RegimeSnapshot`/`RegimeResult`,
  `governing_4h`, `RegimeClassifier`.

## Key contracts

* **Consumes Phase 1 only:** input is `MarketDataResult`; gate = `usability !=
  INVALID` AND `quality.contiguous` AND non-empty. Gaps/INVALID/EMPTY → no
  features (reason flagged). Never re-fetches or bypasses Phase 1.
* **Look-ahead safe:** causal recurrences (index `t` uses only `≤ t`), no
  centered windows, incomplete candles already excluded by Phase 1. Verified by
  a prefix-invariance test.
* **Numerical policy:** money stays Decimal (Phase 1); indicators are float.
  Decimal→float happens **once** at the FeatureBuilder boundary with finite
  validation (non-finite → `NON_FINITE`); no NaN/inf ever in a snapshot. RSI
  flat series (both averages 0) → 50; zero-loss → 100; zero-gain → 0.
* **Warm-up:** SMA-seeded EMA; `warm=False`/`None` before ready; never fabricated.
* **Staleness is BUILD/SERIES-level only** — `FeatureResult.stale` and
  `RegimeResult.stale` (from Phase 1 `quality.stale`). **Not** on
  `FeatureSnapshot`/`RegimeSnapshot` (a historical candle is not "stale";
  mislabeling would corrupt backtest semantics). `warm` is the per-snapshot flag.
* **Regime (descriptive):** trend from EMA50/200 separation vs `trend_band`
  (strict `>`/`<`; equality → RANGING); volatility from `ATR_pct = ATR/close`
  vs `vol_low_pct`/`vol_high_pct` (strict; equality → NORMAL); `0.02` = 2%.
  Thresholds are **provisional, versioned config — not calibrated in P2**
  (calibration is P4/backtesting).
* **1h/4h:** 1h primary; 4h confirmation via `governing_4h` — the latest 4h
  feature with the **same source + same symbol** and `close_time ≤ 1h close_time`
  (equality eligible; future ineligible; source/symbol mismatch never accepted;
  no resampling). `RegimeSnapshot.source/symbol` come from the 1h primary.
* **Provenance/versioning:** `INDICATOR_SET_VERSION`, `REGIME_VERSION`, and
  effective `config_version` on results. Features/regime are a pure function of
  (Phase 1 candles + versioned config) → reproducible; no persistence table.

## Configuration (`app/config.py`)

`ema_short`, `ema_long`, `rsi_period`, `atr_period`, `regime_trend_band`,
`regime_vol_low_pct`, `regime_vol_high_pct` — validated (`0 < ema_short <
ema_long`, periods > 0, `0 < vol_low < vol_high`). `Settings.indicator_config()`
/ `regime_config()` build the dataclasses. Source of truth = `IndicatorConfig`/
`RegimeConfig`.

## Tests

`tests/test_indicators_*.py`, `tests/test_regime_*.py` + `tests/fixtures/market_data.py`.
Known-reference EMA/RSI/ATR, RSI guards (incl. flat→50), prefix-invariance,
finite handling, gate paths, warm-up, 4h governing A–F (source/symbol isolation
+ close_time), trend/volatility boundary equality, confirmation, build-level
stale combos. Deterministic, offline. All Phase 0/1 tests remain green.

## Next phase

**P3 — Cost System** (separate, explicitly authorized prompt). Do not begin
automatically. Real network/exchange adapter (CCXT), additional indicators, and
feature persistence remain deferred.
