# Architecture (Phase 0 view)

The authoritative architecture is the **Master Plan**
(`/Users/josh/.claude/plans/curious-stargazing-chipmunk.md`). This file records
only the Phase 0 foundation and the schema direction for later phases. It does
not duplicate the Master Plan.

## Layering (Phase 0)

```
app/config.py        typed settings (fail-closed, safe defaults)
app/logging_config   structured logs + secret redaction
app/exceptions       AppError hierarchy
app/time_utils       UTC canonical time + monotonic latency helper
app/ids              UUID4 id strategy
app/database         SQLAlchemy engine/session/init + transaction scope
app/models/          Base + mixins + audit models
app/main             offline bootstrap (config -> logging -> db -> validate)
```

Future-phase packages exist as inert boundaries (`market_data`, `indicators`,
`regime`, `strategy`, `costs`, `news`, `ai`, `risk`, `sizing`, `execution`,
`tax`, `portfolio`, `engine`, `notifications`, plus `backtesting/`,
`dashboard/`).

## Foundation conventions (all future models follow these)

* **[ENGINEERING]** UUID4 string primary keys (`UUIDMixin`).
* **[ENGINEERING]** Timezone-aware UTC `created_at` (`TimestampMixin`); UTC is
  canonical everywhere (Master Plan §18.1). Timezone conversion only at the
  presentation/reporting layer.
* **[ENGINEERING]** Integer `version` for audit-critical, versioned records
  (`VersionMixin`).

## Audit schema direction (implemented in later phases, NOT in Phase 0)

The Master Plan (§16) requires a broad, reconstructable audit trail. Phase 0
implements only infrastructure models (`system_events`, `errors`,
`config_versions`). The following model families are the **planned direction**
and will be added by the phase that owns them — extending, never rewriting, the
Phase 0 base:

| Model family | Owning phase |
|---|---|
| candles, market_data_snapshots | P1 |
| feature_snapshots | P2 |
| cost_calcs | P3 |
| signals, strategy_versions | P4 |
| news, sentiment, claude_decisions, model_versions, prompt_versions | P5 |
| risk_decisions | P6 |
| orders, fills, fees, positions, portfolio_snapshots, pnl, exchange_account_snapshots | P6/P10/P11 |
| backtest_runs | P7 |
| paper_trading_runs | P8/P9 |

Reconstruction target (Master Plan §16): *market snapshot → validation →
features → regime → strategy version → candidate → cost → available news →
Claude input → Claude output (exact model_id + prompt_version) → risk decision →
sizing → execution → actual fill → actual fees → final PnL.*

### External IDs & idempotency (reserved, not implemented)

Internal IDs are UUID4 (`app/ids.py`). External/exchange IDs and idempotency
keys (`clientOrderId`, Master Plan §18) get their own dedicated columns in the
execution models when those are built (P6/P10/P11) — never conflated with
internal IDs.

## Model abstraction (AI) — reserved

**[ENGINEERING]** Claude model selection uses **class-based abstraction**
(Haiku/Sonnet/Opus class) resolved from versioned configuration at runtime and
verified at implementation time (Master Plan §0.1-2). Model IDs are never
hardcoded in business logic; the exact `model_id` used is recorded for audit.
Not implemented in Phase 0.

## Tax layer — reserved

**[ENGINEERING]** Tax is a separate, config-driven reporting layer
(`TaxRuleProvider`, Master Plan §0.1-1), never part of the per-trade cost model
and never hardcoded rates. Jurisdiction-portable (Italy now, Azerbaijan later).
Not implemented in Phase 0.
