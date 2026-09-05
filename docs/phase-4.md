# Phase 4 — Strategy + Candidate Generation + Position Sizing

Deterministic, offline, exchange-agnostic, versioned. Turns Phase 2 features into
long-only **candidate** signals, applies the **reward:risk gate** (the §4 half
deferred from P3) and the **P3 cost gate**, and computes an advisory
**risk-budgeted position size**. Computed on demand; no persistence table, no new
dependencies, no order-book data.

Authoritative design: the Master Plan (`/Users/josh/.claude/plans/curious-stargazing-chipmunk.md`, §3, §4, §5, §6, §13).

## Baseline hypothesis (hypothesis-first, §5 — NOT "best backtest wins")

One explicitly stated, provisional hypothesis (a *candidate baseline*, not the
final strategy): *in an established up-trend (1h EMA50 > EMA200, confirmed by the
governing 4h EMA50 > EMA200), an RSI pullback offers a long entry whose ATR-based
target clears costs with acceptable reward:risk.* Long-only (§3).

**Contract clarification 1 — provisional model assumption, not a prediction.**
The ATR target and `expected_gross_move_pct = target_atr_mult · ATR_pct` are a
*model assumption* used to size the reward:risk and cost gates. They are **not** a
claim the target will be reached and carry **no predictive-edge claim**. P4 does
**not** calibrate `stop_atr_mult` / `target_atr_mult` / `rr_threshold` /
`rsi_pullback_level` — they are provisional versioned defaults. Empirical
validation and calibration (train/validation/test split, walk-forward, parameter
isolation, robustness, cost-tier scenarios) are **owned by P7**. P4 only makes
that evaluation possible by being pure, versioned, and leak-free.

## Modules

**`app/strategy/`**
* `config.py` — `STRATEGY_VERSION="strat-v1"`; `StrategyConfig`
  (`rsi_pullback_level`, `stop_atr_mult`, `target_atr_mult`, `rr_threshold`,
  `require_4h_confirmation`, `cost_scenario`) + invariants + `version_tag`.
* `models.py` — `SignalDirection` (LONG only), `SignalDecision`, `CandidateReason`,
  `Candidate` (trade params + `edge_assessment` + versions), `SignalEvaluation`
  (per-candle decision, incl. HOLDs), `CandidateResult` (`.candidates` helper).
* `generator.py` — `CandidateGenerator` (stateless): per 1h snapshot →
  warm/finite gate → **own** EMA up-trend → causal 4h confirmation → RSI pullback
  → ATR stop/target → reward:risk gate → **P3 cost gate** → CANDIDATE / HOLD.

**`app/sizing/`**
* `config.py` — `SIZING_VERSION="size-v1"`; `SizingConfig` (`risk_per_trade_pct`,
  `max_single_asset_exposure_pct`, `max_total_exposure_pct`,
  `max_simultaneous_positions`, `correlated_exposure_cap_pct`,
  `correlation_groups` (BTC/ETH), Decimal `min_notional`/`step_size`/`tick_size`/
  `liquidity_cap_quote`) + invariants + `version_tag`.
* `models.py` — `SizingDecision`, `SizingReason`, `PositionPlan`, `SizingResult`.
* `sizer.py` — `PositionSizer.plan(candidate, *, account_equity, current_exposures)`.

## Key contracts

* **Reuses, never re-implements:** the causal 4h helper
  `app/regime/alignment.py:governing_4h`; the P3 `CostManager.assess_edge`
  (`app/costs/manager.py`) is the net-edge authority.
* **Regime boundary:** the strategy computes its **own** strict EMA compare for
  trend; it **never** consumes `RegimeClassifier` labels (regime stays
  descriptive — never a trading signal). A test asserts a sub-`trend_band` EMA
  separation (regime → RANGING) still fires the strategy.
* **Long-only (§3):** down/ranging trends → HOLD; no short/leverage/margin.
* **Reward:risk gate (the §4 half deferred from P3):** `reward:risk =
  target_atr_mult / stop_atr_mult`; below `rr_threshold` → HOLD.
* **Cost gate:** `CostManager.assess_edge(expected_gross_move_pct, atr_pct,
  scenario)`; non-PASS → `COST_GATE_HOLD`. Scenario defaults to Conservative.
* **No look-ahead:** each 1h decision uses only snapshot `t` and a 4h feature with
  `close_time ≤` the 1h `close_time` (`governing_4h`); incomplete candles already
  excluded by P1. Verified by a prefix-invariance test.
* **Fail-safe (rule 7 / §0.1-3):** not-warm / missing / non-finite / degenerate
  (`close`/`atr`/`atr_pct` ≤ 0) / unknown 4h confirmation → HOLD, never a
  permissive candidate.
* **Sizing — risk budgeting (§13):** size from stop-distance + `risk_per_trade_pct`
  of a **required** `account_equity` (no fixed-capital assumption, §H). Quantity
  floored to `step_size` (never exceeds the budget); prices rounded to
  `tick_size`. Structural caps (single-asset, correlated BTC/ETH, total,
  max-simultaneous, conservative non-order-book liquidity) applied as **pure
  functions over caller-supplied `current_exposures`**. Any violation → `NO_TRADE`.
* **Numeric policy:** strategy percentages/prices are `float` (Phase 2 scale);
  sizing money is `Decimal`, with the candidate's float prices converted once at
  the sizing boundary with finite validation.
* **Contract clarification 2 — advisory, pre-runtime only.** A `SIZED`
  `PositionPlan` is a deterministic offline constraint, **not** an order and
  **not** authorization to trade. It never overrides the future **P6 RiskManager
  (final authority), kill-switch, realized-loss/drawdown controls, or runtime
  portfolio state**. The sizer holds no state and issues nothing.
* **Compute-on-demand:** pure function of (features + versioned config + explicit
  inputs); results carry `strategy_version`/`sizing_version` + `config_version`.
  No `signals`/`strategy_versions` table (deferred to P6).

## Configuration (`app/config.py`)

`strategy_*` and `sizing_*` fields, validated fail-closed (delegating to each
dataclass `__post_init__`); `Settings.strategy_config()` / `sizing_config()`
build them. `cost_scenario` is shared with P3. Defaults are illustrative,
exchange-agnostic, and **not calibrated**.

## Tests

`tests/test_strategy_{config,generator}.py`, `tests/test_sizing{,_config}.py`:
config invariants + Settings builders; setup detection; long-only; 4h
confirmation present/absent/disagree; reward:risk gate; cost-gate integration;
warm-up; degenerate/fail-safe; **does-not-consume-regime-label**;
prefix-invariance (no look-ahead); risk-budget math; step/tick rounding;
min-notional; single-asset/correlated/total/max-positions/liquidity caps;
invalid stop; insufficient/scaling equity (no fixed capital); determinism;
version tags. Deterministic, offline. All P0–P3 tests stay green.

## Next phase

**P5 — News + Claude** (separate, explicitly authorized prompt). Do not begin
automatically. The RiskManager (final authority), kill-switch, realized-PnL &
drawdown tracking, paper engine, `signals`/`strategy_versions` tables (P6),
backtesting/calibration (P7), real network/exchange (CCXT), and order-book depth
remain deferred.
