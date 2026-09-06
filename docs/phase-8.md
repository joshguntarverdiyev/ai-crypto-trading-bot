# Phase 8 — Shadow Mode (Real-Time Decision Pipeline, ZERO Execution)

Shadow Mode runs the **exact, unmodified** P1→P6 decision pipeline against real,
current market data and records a **shadow decision** for every processed eligible
boundary. It executes **zero** real orders, changes **zero** exchange state, and
mutates **zero** portfolio/operational state. It answers an *operational*
question — *does the decision system behave correctly and consistently in real
time?* — **not** a financial one. **No edge or profitability is claimed;
profitability is not a P8 exit criterion.** `LIVE_TRADING`/`PAPER_TRADING` stay
fail-closed false. The evolving paper portfolio + statistical validation are
**P9**.

Authoritative design: the Master Plan (§0.1-3, §0.1-4, §2, §6, §7, §8, §9, §13,
§15, §16, §17, §18, §18.1, §F, §H) and the hardened Phase 8 plan.

## Modules (`app/shadow/`)

* `config.py` — `ShadowConfig` + source enums (`MarketDataSource`/`NewsSource`/
  `AIProvider`), all defaulting to the offline `fixture` provider; `SHADOW_ENGINE_VERSION`.
* `engine.py` — `ShadowEngine.process_boundary(...)`: the flat-account decision
  pipeline. Mirrors the P6 ordering but **stops before any execution mutation**.
  Imports no `ledger`/`PortfolioStore` writer and not the P6 `TradingEngine`.
* `recorder.py` — `ShadowRecorder`: atomic per-boundary persistence. Reuses the
  frozen P6 `TickRecorder` writers for `news`/`claude_decisions`/`risk_decisions`
  (single source of truth), plus the shadow-only `shadow_decisions` row. Writes
  **no** operational tables. Idempotent on `(decision_time, symbol)`.
* `runner.py` — `ShadowRunner`: boundary derivation, idempotency, restart-safety,
  missed-boundary gaps, the data-failure policy, DB-failure HALT, clock-drift
  detection, and honoring/tripping the kill switch. Owns persistence + kill-switch
  mutation; the engine stays side-effect-free.
* `store.py` — `open_shadow_run`/`close_shadow_run`: the `shadow_runs` index with a
  **secret-free** config snapshot.
* `alerts.py` — pure builders for outbound (redacted) shadow alerts; never trade.
* `build.py` — `build_shadow_system(settings, session_factory)` factory. Resolves
  the (offline-default) sources and is **fail-closed** on `live_trading`/`paper_trading`.
* `models.py` — in-process `ShadowResult`/`ShadowOutcome`.

Real adapters (behind the frozen P1/P5 interfaces, **off by default**, lazy imports,
never exercised by the offline suite): `app/market_data/ccxt_adapter.py`
(public/keyless OHLCV), `app/news/http_adapter.py` (CryptoPanic), and
`app/ai/anthropic_provider.py` (advisory Claude). New ORM: `app/models/shadow.py`
(`ShadowDecisionRecord`, `ShadowRunRecord`). CLI: `scripts/run_shadow.py`.

## Flat per-tick account (the P8/P9 boundary)

Each boundary evaluates against a **fresh hypothetical account** (config starting
equity, zero open positions). There is **no evolving book**, no accumulated PnL,
and no virtual positions carried across ticks — that is deliberately deferred to
**P9 Paper Validation**. On APPROVE the would-be order/fill is computed with the
**pure** `PaperBroker.simulate` (returns a value, mutates nothing) and recorded as
**HYPOTHETICAL** only.

## Timing, idempotency, and warm-up

* **Boundary** = the most recently *completed* primary-timeframe (1h) candle close;
  `decision_time` derives from that close, never wall-clock. Multi-symbol
  boundaries run in canonical order (`sorted(symbols, key=str)`).
* **Idempotency**: a durable `shadow_decisions` row for `(decision_time, symbol)`
  short-circuits **before** any provider call → no duplicate Claude/news cost; the
  runner is restart-safe.
* **Missed boundaries** (`backfill_boundaries=0`): recorded as a `shadow.gap`
  system event, **never** as a `shadow_decisions` row.
* **Warm-up (§6.1)**: requires `IndicatorConfig.min_history` (200) + an explicit
  `shadow_warmup_buffer_candles` (default 100) usable **closed** candles — derived
  from the frozen indicator config, never an exchange default. Insufficient
  history **fails closed** (`insufficient_history` HOLD), never misleading indicators.

## Real market data — P1 remains the validation authority

The CCXT adapter is **public/keyless** (constructed with **no** API key/secret;
`exchange_api_key`/`secret` stay empty and are never passed). The exchange id is a
**data-source** choice (config), explicitly not the deferred live-execution
exchange. CCXT output is untrusted raw; the unchanged `MarketDataService`
(closed-candle, staleness, gaps, duplicates, future-tolerance) is the sole
validation authority. Malformed shapes / rate-limit / infra failures raise
`AdapterError` — never a valid-empty success.

## News availability (`available_at <= decision_time`)

The frozen five-timestamp gate is unchanged. An item is eligible only when
`available_at <= decision_time` (and fresh, known-available); `published_at` alone
never makes it eligible, and an item published early but available late is excluded
from that boundary (§7.1). The CryptoPanic adapter is forward-only (no historical
availability fabrication, §8); it must satisfy the frozen `NewsSourceAdapter`
contract (five timestamps, asset tagging, dedup, availability).

## Claude — advisory only

The real Anthropic provider takes the API key at **construction** (never in the
prompt/logs); the model id is runtime-resolved from versioned config and stamped
on every verdict. The frozen state machine is unchanged: disabled/unavailable/
timeout/invalid-JSON/VETO/UNCERTAIN → HOLD; only a valid APPROVE → PROCEED (a
necessary-not-sufficient precondition). Claude can never relax a RiskManager limit.

## External-call vs persistence semantics (at-least-once)

Provider calls happen before the per-boundary commit. If a call succeeds but the
commit fails before durable persistence, a restart **may repeat** the call
(at-least-once) — but never yields a duplicate *durable* decision and never creates
an execution path. No distributed idempotency system is built.

## Failure states (fail closed)

| Condition | Behavior |
|---|---|
| transient market-data/adapter failure | **HOLD** boundary (no decision row) + `shadow.data_failure` event; N consecutive → **PAUSE** (divergence from P6 HALT — no book to protect) |
| stale/gap data | **HOLD** (unchanged usability gate) |
| news/Claude unavailable/timeout/invalid | **HOLD** (frozen analyst state machine) |
| RiskManager daily/weekly-loss/drawdown | record + **HALT** (same classes as P6) |
| RiskManager abnormal spread/slippage | record + **PAUSE** |
| persistence/DB failure | **HALT** (independent session, H9) |
| clock drift > threshold | **PAUSE** + event (§18.1; full NTP is P10) |
| kill switch HALTED/PAUSED | skip new decisions; flat account → **no exit processing** |

## Persistence / audit

Reused (no new columns): `candles` (closed candles), `news`, `claude_decisions`,
`risk_decisions`, `system_events`, `kill_switch_state`. New shadow-only:
`shadow_decisions` (unique `(decision_time, symbol)`), `shadow_runs`. Every
would-be decision is reconstructable: candles + news + claude_decisions (exact
model_id/prompt_version) + risk_decisions + the linking `shadow_decisions` row.

## Dashboard + Telegram

Dashboard adds read-only `GET /api/shadow/decisions` and `/api/shadow/runs`; the
**only** mutations remain the two stop-only controls (pause/halt). Telegram gains
shadow alerts (would-trade labelled **HYPOTHETICAL**, data-failure, kill trips);
inbound stays pause/halt-only. Neither can place, size, or modify a trade.

## Security

`LIVE_TRADING`/`PAPER_TRADING` fail-closed false; the factory refuses to build
otherwise. No trading credentials for Shadow Mode (public/keyless data). The
`anthropic_api_key` only reaches the provider at construction; tokens are redacted
in logs/alerts. Real adapters off by default and never imported by the offline
test suite (fixtures + the network-blocking conftest).

## Dependencies

Optional `[shadow]` extra only (`ccxt`, `httpx`, `anthropic`) — lazily imported,
off by default, never used in tests. The core `app.*` import graph stays free of
them.

## Configuration

`market_data_source` (`fixture`|`ccxt`), `market_data_exchange_id` (required iff
ccxt), `news_source` (`fixture`|`cryptopanic`), `ai_provider` (`fixture`|
`anthropic`), `shadow_primary_timeframe`/`shadow_confirm_timeframe`,
`shadow_starting_equity`, `shadow_warmup_buffer_candles`,
`shadow_max_consecutive_data_failures`, `shadow_backfill_boundaries`,
`shadow_clock_drift_seconds`. All validated fail-closed at load time.

## Tests

`tests/test_shadow_engine.py` (pipeline stages, APPROVE→would-trade, warm-up
fail-closed, published-early/available-late exclusion, kill-switch flat account),
`test_shadow_runner.py` (boundary, canonical order, idempotency/restart, gaps,
data-failure→HOLD/PAUSE, persistence→HALT, clock drift), `test_shadow_no_execution.py`
(zero operational rows + no ledger call + static guard), `test_shadow_persistence_audit.py`
(reconstruction chain, secret-free run snapshot, factory fail-closed),
`test_shadow_restart_external_calls.py` (at-least-once semantics),
`test_ccxt_adapter_normalization.py` (converter + keyless + P1 authority + error
mapping), `test_http_news_adapter.py` (five timestamps, asset tagging, forward-only),
`test_dashboard_shadow_views.py` (read-only, no mutating shadow route),
`test_notifications_shadow_alerts.py` (redaction, hypothetical labelling, inbound
stop-only). All deterministic + offline; all P0–P7 tests stay green.

## Run (offline by default)

```
python -m scripts.run_shadow            # fixture sources → offline, no credentials
pip install -e ".[shadow]"              # real adapters (still no trading, no keys)
```

## Next phase

**P9 — Paper Validation**: an operational evolving paper portfolio + longer-run
statistical/regime validation (`paper_trading_runs`). Deferred beyond P9: live
readiness + tax layer + reconciliation/idempotency + NTP + PostgreSQL (P10), small
live (P11).
