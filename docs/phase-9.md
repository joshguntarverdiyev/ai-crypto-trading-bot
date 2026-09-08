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
- **News (§35.8):** the selected real news adapter is wrapped by a conservative
  settle-margin adapter (`PAPER_NEWS_SETTLE_SECONDS`, default 120) so near-boundary
  news is never over-admitted; the frozen `available_at <= decision_time` gate holds.
- **News provider — Crypto News API (Tier-2 ingestion; `NEWS_SOURCE=cryptonewsapi`):**
  a lightweight poller (`scripts/run_news_ingest`, 15-min cadence) fetches Crypto
  News API and records each article's genuine `first_seen_at` + ingestion provenance
  (provider, token-free request params, HTTP status, response hash, `fetched_at`)
  into an **isolated** ingestion store (`NEWS_INGEST_DB_PATH`, its own SQLite file +
  its own `DeclarativeBase` — the frozen operational schema is untouched). The P9
  runner's decision-time read path (`IngestionStoreNewsAdapter`) reads that store
  with **no boundary network I/O**, so no-look-ahead is defensible. Availability is
  centralized in `SettleMarginNewsAdapter`:
  `available_at = max(published_at + settle, first_seen_at)`. Provider `date`
  (explicit US-Eastern offset, `-0400` EDT / `-0500` EST) is parsed to an aware
  datetime → UTC (never naive→UTC; DST-correct); a missing offset / unparseable date
  rejects the item (no fabricated timestamp). The API **token** is a dedicated secret
  (`CRYPTO_NEWS_API_TOKEN`), config-only, never logged/committed/in provenance, and
  every transport failure raises a token-free `NewsSourceError`. Dedup identity:
  `news_id` → canonical-URL hash → deterministic fingerprint (never random).
  Marketaux remains a drop-in future backup behind the same `NewsSource` interface.

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
# resume an existing run (one sweep per invocation)
python -m scripts.run_paper --run-id <id> --iterations 3
# long-lived, boundary-aligned supervisor (stop with SIGTERM/SIGINT)
python -m scripts.run_paper --run-id <id> --supervise
```
Real sources (public/keyless CCXT OHLCV, CryptoPanic news, Anthropic advisory
analyst) are enabled via config + the `[shadow]` extra; enabling them never enables
trading and never requires a trading key.

### Real-source dependencies (future, meaningful run)
With the default `fixture` sources P9 runs fully offline but the analyst returns
HOLD, so **no paper entry is ever taken and no evidence accrues** — a meaningful
run needs the real (still keyless / advisory-only) sources. Their packages ship in
the **`[shadow]` extra** (`pip install -e '.[shadow]'`): `ccxt` (public/keyless
OHLCV), `httpx` (the CryptoPanic news transport used by `HttpNewsAdapter` — there is
no `requests` dependency), and `anthropic` (advisory Claude). Then set
`MARKET_DATA_SOURCE=ccxt` + `MARKET_DATA_EXCHANGE_ID=<public data-source id>`,
`NEWS_SOURCE=cryptopanic`, `AI_PROVIDER=anthropic`, and supply `ANTHROPIC_API_KEY`
**via `.env`/environment only** (never hardcoded, committed, logged, or placed in a
prompt/config snapshot). CCXT stays public/keyless — no exchange API key/secret and
no private trading API. The 120-second news settle margin
(`PAPER_NEWS_SETTLE_SECONDS`) is preserved by `SettleMarginNewsAdapter`.

### Long-run supervision (macOS; NOT active by default)
For a months-long window, run the **self-scheduling supervisor**
(`--supervise` → `PaperRunner.run()`), which sleeps to each completed 1h boundary
and never advances past real time. Two supported patterns:
- **launchd `KeepAlive` (recommended):** a long-lived `--supervise` process,
  restarted on crash but not after a clean stop. A **non-active template** lives at
  `deploy/launchd/com.aicryptotrader.paper.plist.example` (it is not installed and
  starts nothing; it holds **no secrets** — the app reads `.env` from the
  `WorkingDirectory`). `launchctl unload` delivers SIGTERM → the supervisor stops
  gracefully and releases ownership so the next start resumes instantly.
- **cron / `StartInterval` hourly:** invoke the one-sweep form
  `python -m scripts.run_paper --run-id <id>` once per hour (no `--supervise`).
  Heartbeat then refreshes hourly instead of continuously.

Both are **restart-safe and idempotent**: decisions are keyed on
`(decision_time, symbol)` and fills on `intent_id`, so a crash/restart can never
create a duplicate decision or fill. A hard crash (SIGKILL) leaves the run
resumable via the stale-heartbeat takeover + released OS lock under the same
`--run-id`. Process-manager install, log rotation, and run-DB backup are
operational choices deferred to when the window is actually started.

**Implementation ≠ validation:** a passing implementation does not mean the 3+ month
validation has passed. After implementation, P9 must actually operate for the
required validation window before its evidence is meaningful.

## Redesign: multi-symbol universe + 10-day validation (additive)
- **Universe (`app/universe/`):** a deterministic, reproducible selection of Binance
  USDT spot pairs from a **T0 snapshot** — `quote=USDT`, `status=TRADING`, exclude
  leveraged tokens + stablecoin bases + below a 24h quote-volume floor, then rank by
  24h volume (desc, symbol tie-break), take top `N_max=30` (**effective universe =
  min(30, eligible survivors)**). A runtime warmup/OHLCV-quality screen (frozen P1
  path) drops history-invalid symbols with **no replacement** (B3). The universe is
  **fixed for the whole 10-day window**; the snapshot + `selection_hash` are persisted
  (`paper_universe`) and pre-registered — no look-ahead, no survivorship, no mid-run
  replacement. **Correlation is NOT estimated** (forbidden): cross-asset risk is
  governed by the RiskManager's per-symbol + total exposure caps (documented limit).
- **Positions:** `max_simultaneous_positions=6`; `max_total_exposure_pct=30%`,
  `max_single_asset_exposure_pct=20%`, conservative per-trade sizing/risk — unchanged.
- **OD-3 (portfolio marks):** `RiskManager.evaluate` takes an optional `marks` map so
  the equity / drawdown / daily-loss / weekly-loss gates value the WHOLE open book;
  `marks=None` is byte-identical to frozen P6. This is the ONLY frozen-code change.
- **Claude budget (`app/paper/budget.py`):** `BudgetedAnalyst` (a drop-in
  `ClaudeAnalyst` subclass) caps ACTUAL provider calls per boundary + per run
  (runaway backstops set well above expected); exhaustion → fail-closed
  `HOLD (UNAVAILABLE)` (no provider call, no Claude-less entry). The deterministic
  funnel (universe → data quality → indicators/regime → candidate → cost/edge → news
  → **Claude only here** → RiskManager → PaperBroker) is unchanged; per-boundary
  funnel counters are persisted (`paper_boundary_funnel`) and the per-run count is
  seeded from them for restart-safety.
- **News budget (trial; no purchase):** the poller is global (universe size does NOT
  change news calls). A 3h cadence (`CRYPTO_NEWS_POLL_SECONDS=10800`) → ~80 calls over
  10 days. **Whether the trial cap is 100 TOTAL or per-day is NOT confirmable from
  repo evidence → an explicit pre-runtime blocker** (do not guess); the 80-call target
  is conservative under either. News stays fail-closed (empty/unavailable ⇒ HOLD).
- **10-day gates + verdict:** `validation_days=10` is pre-registered. Gates are
  classified **PASS / FAIL / INSUFFICIENT_EVIDENCE**: operational gates (uptime, gaps,
  data quality) can meaningfully PASS/FAIL in 10 days; statistical gates require
  `min_meaningful_trades=100` (**NOT lowered**) and return INSUFFICIENT_EVIDENCE when
  unmet — a positive 10-day P&L can **never** be PASS on its own. Per-symbol
  concentration + per-symbol P&L are reported. *(An operational-adequacy trade
  threshold below 100 is intentionally left unset pending review — it is NOT the
  statistical bar.)*

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
