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

**Phase 5 — News Intelligence + Claude Analyst (COMPLETE).** Phase 0–4 + the
news pipeline (`app/news/`) and the strictly-advisory Claude analyst veto
(`app/ai/`). News: untrusted items behind a `NewsSourceAdapter` (offline
`FixtureNewsAdapter`) → strict five-timestamp model (§7) → dedup →
availability-gated `NewsContext` (causal `available_at <= decision_time`; unknown
availability excluded; absence is conservative UNAVAILABLE, never "no negative
news"). Analyst: class-based model resolution (`ModelClass` → exact runtime
`model_id` from versioned config, recorded for audit) behind an `AnalystProvider`
(offline `FixtureAnalystProvider`); structured `APPROVE|VETO|UNCERTAIN` →
`PROCEED` only on a clean APPROVE, every failure (invalid schema / unavailable /
timeout / news-unavailable) → HOLD. Deterministic, offline, versioned,
compute-on-demand (audit-complete objects; no tables). No network, no `anthropic`
dependency, no credentials. Claude is **advisory only** — no orders, no
risk-limit changes; the RiskManager (P6) is the final authority. No
historical-news backtest (§8).

## Allowed scope (Phase 0–5)

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
every failure→HOLD — all computed on-demand from injected inputs.

## Forbidden scope (do NOT implement without an explicit next-phase prompt)

**Real news/HTTP fetch (RSS/CryptoPanic) · the `anthropic` SDK / live Claude API
calls · API keys / secrets** · real exchange API / CCXT / network fetch /
WebSocket / live market data · order book · **additional indicators
(MACD/Bollinger/volume-MA)** · **persistence tables (news/claude_decisions/
model_versions/prompt_versions/signals/cost/feature) + repositories** ·
**strategy/cost calibration or any edge/performance claim** · **RiskManager
(final authority) / kill-switch / realized-loss & drawdown tracking / runtime
portfolio state / pipeline orchestration** · backtesting · paper / shadow / live
trading · order execution · `clientOrderId` / reconciliation · stop-loss
execution · Telegram bot · FastAPI/dashboard · tax calculation · exchange
selection · real-money trading · simulated fills · **any fake historical-news
backtest (§8)**. Regime is **descriptive only — never a trading signal.** A
candidate/sized plan is **advisory only**, and the Claude analyst is **advisory
only — never authorization to trade** and never overrides the RiskManager. Do not
create fake implementations. Remaining future-phase packages must stay inert.

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
