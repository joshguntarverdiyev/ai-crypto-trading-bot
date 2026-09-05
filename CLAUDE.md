# CLAUDE.md — project instructions for Claude Code

## What this project is

An AI-assisted cryptocurrency trading **research** system. The objective is to
determine, under realistic costs, execution constraints, and statistical
validation, whether a durable net trading edge exists — **not** to build a bot
that is assumed to be profitable. No profit is ever claimed or guaranteed.

## Source of truth: the Master Plan

The authoritative architecture and scope document is the Master Plan at:

```
/Users/josh/.claude/plans/curious-stargazing-chipmunk.md
```

**Read the relevant sections of the Master Plan before any major architectural
change.** This repo's `CRYPTO_BOT_PLAN.md` is an early, superseded draft — not
authoritative.

## Current phase

**Phase 6 — Risk + Paper Engine (COMPLETE).** Phase 0–5 + the deterministic
**RiskManager (FINAL AUTHORITY)** (`app/risk/`), a **paper (simulated) execution
engine** (`app/execution/`), authoritative portfolio/account state
(`app/portfolio/`), the tick orchestrator (`app/engine/`), and the first
**persistence** layer (`app/models/` news/claude_decisions/risk_decisions/
paper_orders/paper_fills/positions/portfolio_snapshots/kill_switch_state). The
RiskManager is the sole gate to (paper) execution: rule-based, fail-closed,
independently recomputing risk/exposure from authoritative state (never trusting
P4's advisory numbers) and adding runtime controls (daily/weekly loss, drawdown
via persisted HWM, volatility shock, abnormal spread/slippage). Paper fills are
deterministic (reference + adverse spread + slippage only; fees separate; no P3
gate buffers); bot-managed stop/target exits (stop-first when both touch, no
exchange-native stops); `intent_id` idempotency + reconcile-before-retry; atomic
per-tick persistence with an independent-session kill-switch HALT. `LIVE_TRADING`
stays false; offline/simulated only; **paper ≠ live performance**. Claude remains
advisory and can never override the RiskManager.

## Allowed scope (Phase 0–6)

Config, database, models, logging, errors, time/ID utilities, offline bootstrap,
tests, docs, tooling **+ (P1)** exchange-agnostic market-data (canonical
`Candle`/`Ticker`, validation gate, repository/service, offline
`FixtureExchangeAdapter`) **+ (P2)** deterministic indicators/features and
**descriptive** regime classification computed from Phase 1 candles **+ (P3)**
deterministic per-trade cost model + net-edge gate (`app/costs/`) **+ (P4)**
hypothesis-first long-only candidate generation (`app/strategy/`) — incl. the
`reward:risk` gate — and advisory risk-budgeting position sizing with structural
portfolio caps (`app/sizing/`) **+ (P5)** the offline news pipeline (`app/news/`)
and the strictly-advisory Claude analyst (`app/ai/`) behind source/provider
interfaces — class-based model abstraction, structured verdict + strict schema,
every failure→HOLD — all computed on-demand from injected inputs **+ (P6)** the
deterministic RiskManager (final authority) + kill switch (`app/risk/`), the
paper (simulated) execution engine + bot-managed stops (`app/execution/`),
authoritative portfolio/account state + accounting ledger (`app/portfolio/`),
the fail-closed tick orchestrator (`app/engine/`), and the focused persistence
layer (news/claude_decisions/risk_decisions/paper_orders/paper_fills/positions/
portfolio_snapshots/kill_switch_state) — all offline, deterministic, simulated,
with `LIVE_TRADING` fail-closed to false.

## Forbidden scope (do NOT implement without an explicit next-phase prompt)

**Real news/HTTP fetch (RSS/CryptoPanic) · the `anthropic` SDK / live Claude API
calls · API keys / secrets** · **real exchange API / CCXT / live execution /
network fetch / WebSocket / live market data** · order book · **additional
indicators (MACD/Bollinger/volume-MA)** · **strategy/cost/risk calibration or any
edge/performance claim** · **live trading (`LIVE_TRADING` stays false) /
real-money trading / real order execution / real-exchange reconciliation /
`clientOrderId` to a venue / exchange-native stops** · leverage / futures /
margin / shorting · HFT / scalping · backtesting · shadow-mode runtime · Telegram
bot / Telegram trading · FastAPI/dashboard / dashboard trading · tax calculation
· exchange selection · NTP/clock-drift · PostgreSQL migration · **any fake
historical-news backtest (§8)**. Regime is **descriptive only — never a trading
signal.** A candidate/sized plan is **advisory only**, and the Claude analyst is
**advisory only — never authorization to trade** and never overrides the
RiskManager (the deterministic final authority). Paper performance is never
claimed to equal live. Do not create fake implementations. Remaining future-phase
packages must stay inert.

## Non-negotiable rules

1. **Never skip phases.** Each phase has explicit exit criteria; the next phase
   starts only after they pass.
2. **A user request to add a feature is NOT authorization to bypass a phase
   gate.** If asked to implement future-phase work, stop and confirm the phase
   boundary explicitly.
3. **Never enable live trading by default.** `LIVE_TRADING` defaults to `false`
   and must fail-closed. Live trading stays disabled until the Master Plan's
   live-readiness gates (P10/P11) are explicitly satisfied.
4. **Never invent credentials** or commit anything credential-like. `.env` is
   git-ignored; `.env.example` holds empty placeholders only.
5. **Claude/AI must never** hold exchange credentials, place orders, or override
   the RiskManager. The RiskManager is the final authority.
6. **Never silently modify the architecture.** If you find a contradiction that
   cannot be resolved without changing the Master Plan, STOP and report it — do
   not change the Master Plan silently.
7. **Unknown financial or system state is never treated as safe.** Missing data,
   an unavailable model, or an unknown order state must lead to the conservative
   action (HOLD / NO TRADE), never to a permissive assumption.
8. **Model IDs are not hardcoded.** Use class-based abstraction resolved from
   versioned configuration; the exact model ID used is recorded for audit.
9. **UTC is canonical** for all persisted timestamps; timezone conversion only
   at the presentation layer.

## Security principles

No secrets in code or logs (redaction is enforced). Withdrawal-disabled API
keys, IP restriction, and secrets manager are required before any live phase.
Do not log full configuration/environment.

## Testing requirements

Tests must be deterministic and offline (no external network). Financial and
safety logic must be covered by tests before the corresponding phase is
considered complete. Do not remove a safety control to make a test pass.

## Documentation

Keep `docs/` and this file consistent when architecture or financial logic
changes. Distinguish `[RESEARCH]`, `[ENGINEERING]`, and `[ASSUMPTION]` where
relevant, mirroring the Master Plan.
