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

Implemented packages: `market_data`, `indicators`, `regime`, `strategy`, `costs`,
`news`, `ai`, `risk`, `sizing`, `execution`, `portfolio`, `engine` (P1–P6),
**P7** `backtesting/`, `dashboard/`, and `app/notifications/`, plus **P8**
`app/shadow/` (Shadow Mode — real-time decision pipeline, zero execution; real
adapters `app/market_data/ccxt_adapter.py`, `app/news/http_adapter.py`,
`app/ai/anthropic_provider.py` behind the frozen P1/P5 interfaces, off by default),
and **P9** `app/paper/` (Paper Validation — an evolving paper portfolio over the
frozen P1→P6 pipeline; **zero real orders**). The only remaining inert
future-phase boundary is `app/tax/` (P10).

### P8 Shadow vs P9 Paper (architectural boundary)

Both run the exact, unmodified P1→P6 decision pipeline against real/current market
data, real news, and the advisory Claude analyst, with the **RiskManager as the
deterministic final authority** and fills only via the **pure `PaperBroker`** —
**no real exchange execution, no trading credentials.** They differ only in the
account/execution model:

* **P8 Shadow** (`app/shadow/`) — a **flat per-tick hypothetical account**; the
  fill is a pure, non-mutating `PaperBroker.simulate` recorded as HYPOTHETICAL;
  writes only `shadow_decisions`/`shadow_runs`; never imports the P6 `TradingEngine`.
* **P9 Paper** (`app/paper/`) — an **evolving paper portfolio** driven by the frozen
  P6 `TradingEngine` (real `PortfolioStore`/`ledger`/atomic persistence). Key
  P9 architecture:
  * **Per-run database isolation (D-ISO):** each run has its OWN SQLite file
    (`{paper_runs_dir}/{run_id}.db`) with all operational + audit state; the MAIN
    DB holds only the `paper_trading_runs` catalog. No cross-DB foreign keys; no
    `paper_run_id` columns on frozen P6 tables; disjoint `intent_id` namespaces.
  * **Ownership:** OS file lock (live single-writer guard) + catalog
    `owner_token`/`heartbeat_at` (crash takeover). Missing/ mismatched run identity
    fails closed; a known run DB is never silently recreated.
  * **KillSwitch semantics:** PAUSED = no new entries, protective exits continue;
    HALTED = no new entries, **protective exits still run** via the additive
    `TradingEngine.run_protective_exits` (reuses the frozen `_try_exit`).
  * **DB-failure fail-closed:** during HALT, protective exits run only if a DB
    writability probe passes; otherwise the exit is **deferred, never fabricated**
    (atomic rollback ⇒ position stays open, retried on recovery).
  * **Multi-symbol marks (OD-2):** an optional `marks` map values the whole book
    for equity/HWM/drawdown/risk; `marks=None` is byte-identical to frozen P6.
  * **Temporal integrity:** market `close_time <= decision_time`, news
    `available_at <= decision_time` (with a conservative settle margin), consolidated
    end-of-boundary snapshot with `snapshot_time > decision_time`.

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
| **candles — IMPLEMENTED (P1)**; market_data_snapshots deferred | P1 |
| feature_snapshots — **P2 computes features/regime on-demand (no table; deferred)** | P2 |
| cost_calcs — **P3 computes costs on-demand (no table; deferred)** | P3 |
| signals, strategy_versions — **P4 computes candidates/sizing on-demand (no table; deferred to P6)** | P4 |
| news, claude_decisions — **IMPLEMENTED (P6)**; model_versions/prompt_versions denormalized onto claude_decisions; sentiment deferred | P5/P6 |
| risk_decisions — **IMPLEMENTED (P6)** | P6 |
| paper_orders, paper_fills, positions, portfolio_snapshots, kill_switch_state — **IMPLEMENTED (P6, paper)**; orders/fills/fees to a real venue + exchange_account_snapshots deferred | P6/P10/P11 |
| **backtest_runs — IMPLEMENTED (P7)** (research index; full artifacts on the filesystem) | P7 |
| **shadow_decisions, shadow_runs — IMPLEMENTED (P8)** (shadow-only audit; not operational) | P8 |
| **paper_trading_runs — IMPLEMENTED (P9)** (MAIN-DB run catalog/ownership only); **paper_decisions + operational tables live in each run's OWN DB** (per-run isolation, D-ISO) | P9 |

Reconstruction target (Master Plan §16): *market snapshot → validation →
features → regime → strategy version → candidate → cost → available news →
Claude input → Claude output (exact model_id + prompt_version) → risk decision →
sizing → execution → actual fill → actual fees → final PnL.*

### External IDs & idempotency (reserved, not implemented)

Internal IDs are UUID4 (`app/ids.py`). External/exchange IDs and idempotency
keys (`clientOrderId`, Master Plan §18) get their own dedicated columns in the
execution models when those are built (P6/P10/P11) — never conflated with
internal IDs.

## Model abstraction (AI) — implemented as an offline interface (P5)

**[ENGINEERING]** Claude model selection uses **class-based abstraction**
(Haiku/Sonnet/Opus class) resolved from versioned configuration at runtime and
verified at implementation time (Master Plan §0.1-2). Model IDs are never
hardcoded in business logic; the exact `model_id` used is recorded for audit.
Implemented in P5 as `app/ai/config.py` (`ModelClass` → `AIConfig.resolve_model_id`)
+ `AnalystProvider` (`app/ai/provider.py`), stamped onto every `AnalystVerdict`.
The **real Anthropic SDK call is deferred** behind `AnalystProvider` (offline
`FixtureAnalystProvider` in P5; no dependency, no network, no credentials).

## Tax layer — reserved

**[ENGINEERING]** Tax is a separate, config-driven reporting layer
(`TaxRuleProvider`, Master Plan §0.1-1), never part of the per-trade cost model
and never hardcoded rates. Jurisdiction-portable (Italy now, Azerbaijan later).
Not implemented in Phase 0.
