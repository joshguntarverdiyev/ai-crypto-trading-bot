# Phase 7 — Backtesting, Statistical Validation, Dashboard & Telegram

Offline, deterministic **research and observability tooling**. Phase 7 builds the
machinery to ask *"is there a durable net edge?"* honestly — it does **not**
trade, calibrate, optimize, or claim performance. `LIVE_TRADING` stays
fail-closed false; no exchange/CCXT/network/credentials; Shadow Mode is **P8**.

Authoritative design: the Master Plan (§8, §9, §10, §11, §12, §14, §16, §17, §19,
§D, §F, §G, §H) and the Phase 7 plan
(`~/.claude/plans/phase-7-backtesting-dashboard-telegram.md`).

## Modules

* `backtesting/` — pure-quant historical replay + analysis:
  * `dataset.py` — offline CSV snapshot loader; reuses the **P1 validation gate**;
    fail-closed on structural errors or **gaps**; SHA-256 content hash (§22).
  * `engine.py` — the **global chronological multi-symbol event loop** (§9.1).
  * `metrics.py` / `statistics.py` / `robustness.py` — evidence-set metrics,
    seeded bootstrap CI / autocorrelation / outlier dependence, seeded Monte
    Carlo + trade-removal + segmentation + cost-scenario sweep (pure-Python).
  * `walkforward.py` — chronological split + walk-forward + **pre-registration**
    threshold guard (§G).
  * `benchmark.py` — buy-and-hold **context only** (§0.1-5).
  * `report.py` / `store.py` — evidence-set report (mandatory §21 disclaimer +
    §8.1 survivorship note) + filesystem artifacts + a `backtest_runs` index row.
* `dashboard/` — FastAPI **read-only** monitoring over the P6 audit tables + the
  `backtest_runs` index, plus the **only two mutating endpoints**
  (`POST /control/pause`, `POST /control/halt`) wired to the existing
  `KillSwitch`. Loopback + token-gated; it cannot place/size/modify a trade.
* `app/notifications/` — Telegram outbound alerts + optional inbound **pause/halt
  only**, behind a `NotificationTransport` interface (offline fixture default;
  real HTTP transport off/deferred, never used in tests). Never trades.
* `app/models/backtest.py` — `BacktestRunRecord` (research index; separate from
  operational tables).

## Reuse of frozen P0–P6 contracts (no duplication)

The backtester **imports and calls** the unmodified pure functions —
`FeatureBuilder` (P2) → `CandidateGenerator`+`CostManager` (P4/P3) →
`PositionSizer` (P4) → `RiskManager` (P6) → `PaperBroker` + `compute_exit_intent`
(P6) → `ledger` (P6) — with in-memory state. **One** RiskManager, **one**
CostManager. It writes **no** operational tables, instantiates **no** real
`KillSwitch`/DB, and imports **no** P6 runtime engine or news/Claude runtime.

## Backtest semantics (correctness)

* **Global event ordering (§9.1):** one loop ordered by `(decision_time,
  canonical_symbol_rank)` where rank = index in `sorted(symbols, key=str)` —
  **input-order-independent** (reverse-order test). One shared `AccountState`.
  Same-boundary approved entries are **reserved** against a `provisional` account
  (via the frozen `ledger.apply_entry`) so correlated/total/cash caps cannot be
  breached by two same-timestamp signals; the reservation is discarded at
  boundary end; the authoritative fill happens at the entry event.
* **No look-ahead (§10):** a candle influences a decision only if
  `close_time <= decision_time`. Features/candidates are causal (P2 recursions +
  causal `governing_4h`), so per-boundary indexing is provably identical to
  per-boundary windowing (append/truncate leakage tests).
* **Entry fill modes (§10, versioned):** **`next_open` (default)** = execution
  reference is bar *i+1* **open** (never its H/L/C for the decision or size);
  **`signal_close`** = bar *i* close. Both execute only at the next boundary.
* **Decision-time frozen sizing (§13):** sizing/risk use only data known at
  `decision_time`; the plan is frozen — no future/mark-to-market can change
  `plan.quantity` (regression test).
* **Costs (§12):** the P3 gate decides tradability; the `PaperBroker` applies
  adverse half-spread + slippage + a separate taker fee (H1). P3 `min_net_edge`
  buffers are **never** re-subtracted from realized PnL (no double count). Headline
  scenario is **conservative**; a sweep covers optimistic/base/conservative.
* **Stops/target/gap (§16):** inherited from `compute_exit_intent` (stop-first,
  gap-through worse, target never optimistic); re-asserted through the engine.
* **HALT/PAUSE (§14):** an in-memory kill state; HALT-class reasons end the run by
  default (`end_run`, matching production manual-reset), PAUSE stops new entries.

## Historical news / Claude boundary (§8 / §21)

The backtest is **pure-quant**: no `NewsService`/`ClaudeAnalyst`, no `anthropic`
SDK, **no fabricated historical AI**. Because the `RiskManager` requires a
`PROCEED` verdict, the engine passes a **structural sentinel** `AnalystVerdict`
(`model_id="__backtest_quant_only__"`) that is **never persisted**. As the veto is
HOLD-only, the pure-quant result is an **upper bound on trade frequency**. Every
report carries the standard disclaimer.

## Statistics discipline

Reports emit an **evidence set**, never a boolean approval (§11). Sample size is
an operational floor, not significance; a positive bootstrap CI is necessary but
**not sufficient**; Monte Carlo assumes independence (cross-check
autocorrelation); buy-and-hold is context, not a gate. There is **no optimizer /
no automated parameter search** (guard test); calibration is a separate,
protocol-governed research activity, not a code deliverable.

## Security

`LIVE_TRADING` fail-closed. Dashboard loopback + token (the two controls are the
only mutations; resume/reset stays a privileged out-of-band operator action).
Telegram fixture-only in tests; real token empty in the repo; `dashboard_auth_token`
is a redacted secret. No exchange/Claude credentials anywhere.

## Dependencies

Backtest engine + all metrics/statistics/Monte-Carlo are **pure-Python** (stdlib
`math`/`statistics`/`random`) — no numpy/scipy/pandas. The dashboard adds an
optional `[dashboard]` extra: `fastapi`, `uvicorn`, `httpx` (in-process offline
`TestClient`). The core `app.*` import graph stays FastAPI-free.

## Tests

`tests/test_backtest_*` (dataset, determinism, global-ordering + same-timestamp
cap, entry-fill-modes, decision-time-sizing, no-lookahead, costs, stops/gaps,
metrics/statistics/robustness/walk-forward/benchmark, sentinel-boundary,
persistence + operational isolation, no-optimizer guard),
`tests/test_dashboard_*` (read views, controls+auth, two-stop-only-routes +
no-trade), `tests/test_notifications_*` (fixture, inbound allow-list, no-trade).
All deterministic + offline; all P0–P6 tests stay green.

## Run (offline)

```
python -m scripts.run_backtest       # loads data/backtests/datasets/<name>, writes artifacts + a run row
pip install -e ".[dashboard]" && python -m scripts.run_dashboard   # read-only dashboard on loopback
```

## Next phase

**P8 — Shadow Mode**: the full real pipeline (data+indicators+strategy+**news+
Claude**+risk/cost) with **no execution/fill**; failure-state exercise;
`paper_trading_runs`. Deferred beyond P8: paper validation (P9), live readiness +
tax layer + reconciliation/idempotency + NTP + PostgreSQL (P10), small live (P11).
