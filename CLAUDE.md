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

**Phase 0 — Foundation (COMPLETE/IN PROGRESS).** Foundation infrastructure only.

## Allowed scope (Phase 0)

Configuration, database, models, logging, errors, time/ID utilities, offline
bootstrap, tests, documentation, project/dev tooling.

## Forbidden scope (Phase 0 — do NOT implement)

Exchange API / CCXT / market data / WebSocket / OHLCV / order book · indicators
· regime detection · strategy / candidate signals · backtesting · paper / shadow
/ live trading · order execution · `clientOrderId` / reconciliation · stop-loss
execution · position sizing / risk engine · kill-switch runtime behavior · news
/ RSS / sentiment · Anthropic/Claude API calls · Telegram bot · FastAPI/dashboard
· tax calculation · exchange selection · API keys / secrets · real-money trading
· simulated fills. Do not create fake implementations to make things "look
complete." Future-phase packages must remain inert.

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
