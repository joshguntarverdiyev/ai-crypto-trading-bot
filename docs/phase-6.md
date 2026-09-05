# Phase 6 — Risk + Paper Engine

The deterministic **RiskManager (final authority)**, a **paper (simulated)
execution engine**, authoritative **portfolio/account state**, and the first
**persistence** layer, wired into a fail-closed **P4→P5→P6** tick. Offline,
deterministic, versioned. `LIVE_TRADING` stays false; no real exchange, network,
credentials, or live execution. **Paper performance is never claimed to equal
live.**

Authoritative design: the Master Plan (§6, §9, §13, §15, §16, §17, §18, §18.1, §D)
and the hardened P6 plan (H1–H13).

## Modules

* `app/risk/` — `RiskConfig`, `RiskManager` (final authority), `KillSwitch`
  (RUNNING/PAUSED/HALTED, persisted independently), `MarketState`/`RiskAssessment`.
* `app/execution/` — `PaperConfig`, order state machine + types, `PaperBroker`
  (deterministic simulated fills), `stops` (bot-managed stop/target exits),
  `PaperExecutionRepository` (idempotency + reconcile).
* `app/portfolio/` — `Position`/`AccountState`, pure `ledger` (H12 accounting),
  `PortfolioStore` (DB-authoritative reads + restart rebuild + UTC baselines).
* `app/engine/` — `TradingEngine.process_tick` (orchestration), `TickRecorder`
  (atomic per-tick persistence).
* `app/models/` — `NewsRecord`, `ClaudeDecisionRecord`, `RiskDecisionRecord`,
  `PaperOrderRecord`, `PaperFillRecord`, `PositionRecord`,
  `PortfolioSnapshotRecord`, `KillSwitchRecord`.

## Pipeline (fail-closed; RiskManager is the sole execution gate)

```
market data → usability → features → candidate (embeds P3 cost gate + R:R) →
news → Claude analyst → sizing (authoritative equity) → RiskManager (FINAL
AUTHORITY) → plan validation → paper execution → portfolio update → atomic persist
```

Open positions are checked for stop/target exits first (exits run even while
PAUSED; new entries do not). Any missing/invalid/unavailable input ends the tick
in HOLD; systemic failures trip the kill switch. Claude's verdict is an advisory
PROCEED precondition — never sufficient, and it can never relax a limit.

## RiskManager — final authority

APPROVE (proceed) / HOLD (precautionary, no trade this tick) / REJECT (violation,
logged). It **independently recomputes** per-trade risk and exposure from actual
plan fields against authoritative account state (H6) — P4's numbers are advisory
only. Controls: per-trade risk, single-asset, total, correlated (BTC/ETH),
max-simultaneous, insufficient cash, plus **runtime-only** daily/weekly loss
(UTC calendar baselines, H4), drawdown (persisted HWM, H5), volatility shock, and
abnormal spread/slippage (from the injected `MarketState`, H8).

### P4 sizing vs P6 RiskManager

P4 `PositionSizer` is advisory/structural over caller-supplied inputs. P6
`RiskManager` is binding, uses authoritative state, adds runtime controls, and
overrides a SIZED plan. Only the RiskManager authorizes (paper) execution.

## Paper engine

Deterministic, no RNG. **Fill price = reference + adverse directional spread +
adverse slippage only (H1)** — no P3 gate buffers; **fees booked separately** from
the taker fee. Partial fills/rejects are rule-based; partials use the configured
`liquidity_fill_cap` (a **simulation assumption**, not observed liquidity, H7).
Order state machine `INTENDED→SUBMITTING→SUBMITTED→{FILLED|PARTIAL|REJECTED|
CANCELED|UNKNOWN}` (§18). **Stops are bot-managed — no exchange-native stops.**
Stop triggers on `low≤stop`, target on `high≥target`; **both-touched → conservative
stop-first (H2)**; gap fills at the worse open; target ignores a favorable gap.

## Portfolio/account state

DB-authoritative; the in-memory `AccountState` is rebuilt from persisted positions
+ the latest snapshot on restart (H11). The pure ledger books cash/PnL/fees with
**no double-counting** (H12): entry/exit fees each once, realized PnL only on
exit, equity = cash + Σ open·mark, unrealized never mixed into realized. Positions
are **self-contained** (incl. stop/target, H10) — open-position risk never needs
the Candidate. Exposure reuses correlation grouping.

## Persistence (focused set)

| Table | Idempotency | Notes |
|---|---|---|
| `news` | unique `(source, dedup_key)` | 5-timestamp audit |
| `claude_decisions` | UUID | denormalized exact `model_id`/`model_class`/`prompt_version` (§16) |
| `risk_decisions` | UUID | binding outcome + limits snapshot |
| `paper_orders` | **unique `intent_id`** | idempotency key (§18) |
| `paper_fills` | UUID (append-only) | FK order |
| `positions` | one OPEN per symbol (repo-enforced) | self-contained (H10) |
| `portfolio_snapshots` | UUID | cash/equity/PnL/fees + HWM (H4/H5) |
| `kill_switch_state` | singleton | HALT survives restart (H9) |

Reused: `system_events`, `config_versions`. No `model_versions`/`prompt_versions`/
`sentiment` tables (versions are denormalized). Append-only; UTC timestamps.

## Idempotency & reconciliation (paper scope)

`intent_id` (deterministic from decision_time+symbol+strategy_version) is unique;
reconcile-before-retry returns an existing terminal order — never a duplicate
fill. **Implemented in P6:** paper state machine + idempotency + reconcile against
the paper store. **Deferred to P10/P11:** real-exchange reconciliation, venue
`clientOrderId`, network-timeout/unknown-fill handling.

## Kill switch / failure states

Tick-level fail-safe HOLD (stale/unavailable data, invalid candidate/verdict,
news unavailable, single risk HOLD) leaves state unchanged. Trips: **PAUSE**
(recoverable — abnormal spread/slippage; auto-resume under safe conditions) and
**HALT** (critical — daily/weekly loss, drawdown, persistence failure, unknown/
unexpected; manual reset required). HALT is written in an **independent session**
so a rolled-back tick can never lose it (H9), and it survives restart.

## Time integrity

UTC canonical; `decision_time`/`now` injected into all business logic (no
uncontrolled wall-clock). Audit stamps (`created_at`/`processed_at`/latency) use
runtime UTC and are excluded from determinism assertions (H3). NTP/clock-drift
deferred to P10.

## Security (unchanged)

`LIVE_TRADING` false (fail-closed). No API keys, live exchange, CCXT, network,
withdrawals, Telegram/dashboard trading, or Claude credentials. Paper only.

## Tests

`tests/test_risk_config.py`, `test_risk_manager.py`, `test_kill_switch.py`,
`test_paper_broker.py`, `test_execution_stops.py`, `test_portfolio_ledger.py`,
`test_engine_integration.py`, `test_persistence.py`, `test_halt_persistence.py`
(+ `tests/_p6_helpers.py`): RiskManager APPROVE + every control (H6/H8);
kill-switch classes + restart; deterministic fills/partials/rejects/fees (H1/H7);
stop/target/gap/both-touched (H2); ledger no-double-count (H12); full P4→P5→P6
integration (APPROVE/HOLD/REJECT/kill); idempotency (no duplicate fill);
restart-recovery (H11); persistence + news idempotency; HALT persistence + atomic
rollback (H9); determinism (H3). Deterministic, offline. All P0–P5 tests stay green.

## Corrective-pass policies (post-audit)

- **Daily/weekly loss baseline (D1):** the period baseline is the latest snapshot
  **strictly before** the UTC-day/ISO-week boundary (carry-forward), else
  starting equity — never an in-period snapshot. A losing first trade in the
  period is therefore fully counted. (`portfolio/store.py::baseline_equity`.)
- **Risk audit snapshot (J-ev):** `RiskAssessment.evaluated` carries the
  configured limits **and** observed/computed values (equity, trade risk, each
  exposure + cap, losses, drawdown, ATR%, spread, slippage, staleness), as a
  deterministic string map persisted to `risk_decisions.evaluated`.
- **Decision idempotency (E43):** a P6 tick's decision identity is
  `(decision_time, symbol)`. Reprocessing the same tick reuses existing
  `claude_decisions`/`risk_decisions` (recorder check-then-skip); `paper_orders`/
  `paper_fills` are protected by the unique `intent_id` + reconcile-before-retry.
- **Look-ahead protection (H58):** business-time eligibility (candle closed-ness
  AND staleness) is evaluated as-of **`decision_time`**, never the ingestion
  `now`; a candle closing after `decision_time` cannot influence the decision.
  Invariant `now >= decision_time` is enforced — a violation fails closed (a
  `time_integrity` HOLD, no trade).
- **Exit-risk boundary:** risk-**increasing** entries require RiskManager APPROVE;
  risk-**reducing**, reduce-only stop/target exits use the dedicated safety path
  (`_try_exit` → `PaperBroker`) and can only close/reduce an existing position —
  they never open or increase exposure and are exempt from the entry gate.
- **HALT exit policy (P6 paper-only):** a HALTED kill switch **freezes paper
  state** — `process_tick` returns before exits, so open positions are not
  processed while HALTED (manual reset required). This is an explicit P6 paper
  policy; exchange-native/offline stop protection during a halt is **deferred to
  the live-readiness phases**.
- **Abnormal spread/slippage:** the RiskManager evaluates these against an
  **injected `MarketState`**. The P6 engine supplies conservative config-derived
  assumptions (no order book / no real observation); a supplied abnormal
  `MarketState` triggers the configured risk response (unit-tested).
- **Auto-resume:** P6 uses **manual** resume only. `KillSwitch.resume()` (PAUSED→
  RUNNING) exists but is **never called automatically** by the engine — a pause is
  sticky; there is no automatic re-entry after a pause. HALT requires
  `manual_reset()`.
- **B-slip (deferred):** the RiskManager validates the **reference/proposed**
  execution risk (`plan.entry_ref`); the `PaperBroker` may realize a worse fill
  via adverse spread/slippage, so realized per-trade risk can slightly exceed the
  reference. P3 decision buffers are **not** double-counted in fills (H1).
  **Fill-aware live risk validation is deferred** to the execution/live-readiness
  phase.

## Next phase

**P7 — Backtesting + Metrics + Dashboard + Telegram** (separate prompt). Deferred:
live trading, real exchange/CCXT, credentials, network, leverage/futures/margin/
shorting, backtesting/calibration, tax, dashboard, Telegram trading, real-exchange
reconciliation, exchange-native stops, NTP/clock-drift, PostgreSQL — all behind
their gates.
