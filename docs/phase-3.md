# Phase 3 — Cost System

Deterministic per-trade **trading-cost model** and the **net-edge gate**: given a
candidate's expected gross move, decide whether an edge survives realistic costs.
No strategy, sizing, risk, news, AI, execution, exchange/network, order book, or
persistence table; no new dependencies. Fully offline and deterministic.

Authoritative design: the Master Plan (`/Users/josh/.claude/plans/curious-stargazing-chipmunk.md`, §4, §9, §10, §14).

## Modules (`app/costs/`)

* `config.py` — `CostConfig` (fee/spread/slippage/buffers/volatility/liquidity as
  decimal-ratio percentages), `CostScenario` (`OPTIMISTIC`/`BASE`/`CONSERVATIVE`),
  `COST_MODEL_VERSION`. Invariants: all values ≥ 0; `maker_fee_pct ≤ taker_fee_pct`;
  strictly increasing scenario multipliers. Source of truth for cost parameters.
* `fees.py` — pure `entry_exit_fee_pct` / `round_trip_fee_pct`; taker both sides
  unless a maker fill is stated.
* `spread.py` — `spread_pct_from_ticker` (`(ask-bid)/mid` from a Phase 1 `Ticker`)
  and `resolve_spread_pct` (live if valid, else conservative fallback flagged).
* `slippage.py` — `slippage_pct` (scenario-scaled execution friction) and
  `volatility_pct` (ATR_pct-driven, capped). Parametric — **no order-book depth**.
* `manager.py` — `CostManager` (stateless): `min_net_edge` (itemized
  `CostBreakdown`) and `assess_edge` (`EdgeAssessment`: PASS/HOLD).
* `models.py` — `EdgeDecision`, `CostReason`, `CostBreakdown`, `EdgeAssessment`.

## Key contracts

* **The §4 min-edge model** is the sum of: `entry_fee + exit_fee + spread +
  slippage + execution_uncertainty + model_uncertainty + safety_margin +
  volatility(ATR_pct) + liquidity`. The gate: `expected_gross_move_pct −
  min_net_edge_pct > 0` (strict) → PASS, else HOLD.
* **Slippage vs volatility are separate** (Master Plan §4): slippage is
  scenario-scaled execution friction; the ATR_pct term is its own `volatility`
  component. ATR is never double-counted, and slippage carries no ATR term.
* **Cost side only.** The `reward:risk >= threshold` half of §4 needs stop
  distance / target (strategy + sizing) and is **deferred to P4**. P3 generates
  no candidates; `assess_edge` is exercised with synthetic inputs.
* **Fail-safe (rule 7 / §0.1-3):** unknown → *more* conservative, never
  permissive. Missing/invalid spread → conservative fallback (`SPREAD_ESTIMATED`);
  missing/non-finite ATR_pct → the volatility **cap** (`MISSING_FEATURE`); a
  missing or non-finite expected move (or non-finite ATR_pct) → **HOLD**
  (`NON_FINITE`). Warnings are surfaced on the result; a HOLD is never silently
  a PASS.
* **Scenario tiers (§10).** `CostScenario` scales slippage; the gate defaults to
  **Conservative** (good only in optimistic ≠ success). `min_net_edge_pct` is
  monotonic in scenario.
* **Numeric policy:** percentages are `float` on the ATR_pct scale (`0.001` =
  0.1%). Money stays `Decimal` (Phase 1); the only Decimal→float conversion is
  deriving spread from a `Ticker`, done once at that boundary with finite guards.
* **Exchange-agnostic & illustrative:** fee/spread/slippage defaults are
  provisional versioned placeholders resolved from config — never a hardcoded
  exchange fee (§0.2-4, §14). **Not calibrated** in P3 (calibration is P7).
* **Tax excluded** from the per-trade cost model (§0.1-1).
* **Compute-on-demand:** costs are a pure function of (inputs + versioned config);
  no `cost_calcs` persistence table (deferred to P4/P6, mirroring P2's stance on
  the feature table). Results carry `cost_model_version` + `config_version`.
* **Regime stays descriptive:** only the raw `ATR_pct` feature feeds the cost
  model; the regime *label* is never used as a cost input.

## Configuration (`app/config.py`)

`cost_taker_fee_pct`, `cost_maker_fee_pct`, `cost_spread_fallback_pct`,
`cost_slippage_base_pct`, `cost_slippage_{opt,base,cons}_mult`,
`cost_atr_vol_coefficient`, `cost_atr_vol_cap_pct`, `cost_liquidity_buffer_pct`,
`cost_execution_uncertainty_pct`, `cost_model_uncertainty_pct`,
`cost_safety_margin_pct`, `cost_scenario` — validated fail-closed (a bad value
raises `ConfigError` at load). `Settings.cost_config()` / `default_cost_scenario()`
build the dataclass/enum. Source of truth = `CostConfig`.

## Tests

`tests/test_costs_{config,fees,spread,slippage,manager}.py`: config invariants +
Settings builders; fee math; spread from ticker + fallback + guards; slippage
scenario-monotonicity and volatility ATR-monotonicity/cap; min-edge component
sum, PASS/HOLD (incl. strict boundary), and every fail-safe path (missing spread,
missing/non-finite ATR, missing/non-finite gross move); scenario monotonicity;
determinism; version tags. Deterministic, offline. All P0/P1/P2 tests stay green.

## Next phase

**P4 — Strategy + Sizing** (separate, explicitly authorized prompt). Do not begin
automatically. The `reward:risk` gate, cost calibration, a `cost_calcs`
persistence table, real network/exchange (CCXT), order-book depth, and additional
indicators remain deferred.
