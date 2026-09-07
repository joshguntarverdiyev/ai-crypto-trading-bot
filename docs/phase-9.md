# Phase 9 — Paper Validation (evolving paper account; NO real trading)

**Status: IMPLEMENTED.** P9 turns the frozen P1→P6 decision pipeline into a
long-running, restart-safe, **evolving paper-trading account** over real/current
market data, real news, and real Claude — with **zero real money, zero real
orders, and no reachable live path.** `LIVE_TRADING`/`PAPER_TRADING` stay
fail-closed **false**; P9 runs ONLY when `PAPER_VALIDATION_ENABLED=true`.

## What P9 is (and is not)
- **Is:** an orchestration + audit + validation layer around the frozen P6
  `TradingEngine` (`app/engine/pipeline.py`). Unlike P8 Shadow Mode's flat
  per-boundary account, P9 carries a persistent portfolio (cash, positions,
  realized/unrealized P&L, drawdown, HWM) across boundaries and survives restart.
- **Is not:** live trading, real orders, exchange trading credentials, futures,
  leverage, shorting, HFT, WebSocket/order-book execution, new indicators,
  strategy/risk/cost calibration, or any profitability claim. **Paper ≠ live;
  P9 success ≠ live-readiness (P10/P11).**

## Architecture (final plan §35)
- **Per-run database isolation (D-ISO):** each run gets its OWN SQLite file
  (`{PAPER_RUNS_DIR}/{run_id}.db`) holding all operational + audit state; the MAIN
  database holds ONLY the `paper_trading_runs` catalog (metadata/ownership). Runs
  cannot contaminate one another — separate files ⇒ disjoint `intent_id`
  namespaces, no shared positions/snapshots, no cross-run metric aggregation. There
  are **no `paper_run_id` columns on frozen operational tables** and **no cross-DB
  foreign keys**; `paper_decisions.paper_run_id` is a run-identity field enforced in
  the application.
- **Engine reuse (OD-1/OD-2):** the ONLY frozen-code touch is two additive,
  default-preserving extensions to `TradingEngine`: `run_protective_exits(...)`
  (protective stop/target exits continue while HALTED; new entries never do) and an
  optional `marks=None` parameter (full multi-symbol decision-time marks for correct
  equity/drawdown/risk). With `marks=None` the engine is byte-identical to P6.
- **Runner (`app/paper/runner.py`):** boundary scheduling, data pre-check + full
  marks, gap detection, clock-drift → PAUSE, data-failure policy → PAUSE after N,
  kill-state routing, per-`(decision_time, symbol)` idempotency, a consolidated
  end-of-boundary snapshot (authoritative equity point, `snapshot_time >
  decision_time`), and the run's ownership heartbeat.
- **Ownership & restart:** single-writer via an OS file lock (live guard) plus a
  catalog `owner_token`/`heartbeat_at` (crash-takeover). A missing known run DB is
  never silently recreated; a run-identity mismatch fails closed.
- **DB-failure fail-safe (§35.2):** protective exits during HALT run only when a DB
  writability probe passes; otherwise the exit is **deferred, never fabricated** —
  the atomic tick rolls back, the position stays OPEN, and it is re-evaluated when
  the DB recovers (at-most-once durable effect via `intent_id`).
- **News (§35.8):** the real CryptoPanic adapter is wrapped by a conservative
  settle-margin adapter (`PAPER_NEWS_SETTLE_SECONDS`, default 120) so near-boundary
  news is never over-admitted; the frozen `available_at <= decision_time` gate holds.

## Accounting & metrics (§35.5, `app/paper/metrics.py`)
- Authoritative equity/return series (total return, drawdown, Sharpe/Sortino/Calmar)
  come from the consolidated `portfolio_snapshots` (fully fee-inclusive).
- Per-CLOSED-trade net P&L is reconstructed **fee-exact** from the fills' cash flows
  (both entry and exit fees) — NOT `ledger.realized_pnl` (which omits the entry fee).
- Reuses the frozen P7 pure-Python tooling (`backtesting/metrics.py`,
  `statistics.py`, `robustness.py`, `walkforward.py`) via a `BacktestResult`-shaped
  view. No numpy/scipy/pandas.
- **Objective, pre-registered gates** (thresholds locked before results are read):
  operational duration/uptime/gaps vs statistical evidence — min meaningful trades;
  **regime coverage** (per CLOSED-trade entry-boundary regime; "observed once" never
  counts → `insufficient_data`); autocorrelation validity; outlier dependence;
  **rolling-expectancy stability** (chronological sign-stability across buckets, via
  the P7 `time_segments`); **top-k concentration** (excessive iff removing the
  best k trades turns expectancy non-positive, via the P7 `trade_removal_curve`);
  and the **Monte-Carlo max-drawdown ceiling** (the seeded, deterministic
  `monte_carlo_max_drawdown` p95 must be ≤ a pre-registered ceiling; `insufficient_data`
  when < 2 trades). The bootstrap CI and the Monte-Carlo drawdown distribution also
  remain available as necessary-not-sufficient **evidence**. No single number
  approves a run. The descriptive regime label is captured at the
  decision boundary by the runner (from the same decision-time candles the pipeline
  uses — never future information, never a trading signal) and persisted on
  `paper_decisions.regime`.

## Surfaces
- **Dashboard:** additive read-only `/api/paper/*` views (each opens a run DB
  read-only from the catalog; no cross-run aggregation). The ONLY mutating endpoints
  remain `/control/pause` and `/control/halt`.
- **Telegram:** additive P9 alert kinds through the existing `Notifier`; inbound is
  still pause/halt-only. Neither can place, size, or modify a trade.

## Running
```
# offline (fixture sources): safe, no network, no credentials
PAPER_VALIDATION_ENABLED=true python -m scripts.run_paper
# resume an existing run
python -m scripts.run_paper --run-id <id> --iterations 3
```
Real sources (public/keyless CCXT OHLCV, CryptoPanic news, Anthropic advisory
analyst) are enabled via config + the `[shadow]` extra; enabling them never enables
trading and never requires a trading key.

**Implementation ≠ validation:** a passing implementation does not mean the 3+ month
validation has passed. After implementation, P9 must actually operate for the
required validation window before its evidence is meaningful.

## Known limitations (by design; not safety issues)
- **News settle margin:** enforced and unit-tested at the adapter level (shifts
  `available_at` forward); the end-to-end integration through the real CryptoPanic
  path is not exercised by the offline suite (it requires the network-bound
  adapter), by design. The frozen `available_at <= decision_time` gate does the
  exclusion.
- **Real-source runtime paths** (CCXT/CryptoPanic/Anthropic) are, by policy, never
  exercised by the offline test suite; they are lazily imported only when selected.

The prior v1 gaps (regime capture + coverage gate, rolling-expectancy stability,
top-k concentration, multi-symbol same-boundary test, open-position accounting
identity test, and failure-injected recovery convergence) are now implemented and
covered by tests.
