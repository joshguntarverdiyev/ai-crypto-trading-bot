# Phase 5 — News Intelligence + Claude Analyst

Deterministic, offline, versioned. A news pipeline (behind a source adapter) and
a strictly-advisory Claude analyst veto (behind a provider abstraction) that
consume a P4 `Candidate` and produce audit-complete objects. No network, no
`anthropic` dependency, no credentials, no persistence table — real RSS/CryptoPanic
HTTP + the Anthropic SDK are deferred behind the interfaces; tables land in P6.

Authoritative design: the Master Plan (`/Users/josh/.claude/plans/curious-stargazing-chipmunk.md`, §6, §7, §8, §0.1-2, §0.1-3, §16, §17).

## News pipeline (`app/news/`)

* `config.py` — `NEWS_PIPELINE_VERSION="news-v1"`; `NewsConfig` (`max_news_age`,
  `dedup_window`, `require_known_availability`, `known_assets`) + invariants +
  `version_tag`.
* `models.py` — `NewsItemRaw` (untrusted DTO); `NewsItem` (strict canonical,
  tz-aware-UTC five-timestamp model); `NewsAvailability`
  (AVAILABLE/STALE/DEGRADED/UNAVAILABLE); `NewsReason`; `NewsIssue`; `NewsContext`
  (the analyst's gated input).
* `adapter.py` / `fixture_adapter.py` — `NewsSourceAdapter` ABC (no I/O) +
  offline `FixtureNewsAdapter` (can simulate a source outage).
* `normalization.py` — raw→canonical; assigns the five timestamps; unknown
  availability flagged + trust lowered; data-quality → `NewsIssue` (never raises).
* `dedup.py` — deterministic first-seen-wins dedup within the window.
* `service.py` — `NewsService` (single consumption point, mirrors
  `MarketDataService`): fetch → normalize → dedup → availability gate → `NewsContext`.

### Five timestamps (§7) and the availability gate

`published_at`, `discovered_at`, `ingested_at` (= injected `now`), `available_at`,
`processed_at` (None until an analyst/sentiment step). **Golden rule:** for a
given `decision_time`, an item is usable only if its availability is **known**
and `available_at <= decision_time` and it is fresh (`decision_time -
published_at <= max_news_age`). A future `available_at` is excluded
(anti-look-ahead); unknown historical availability is excluded when
`require_known_availability` (default) — never assumed available. Overall
availability is conservative (§0.1-3): no items → **UNAVAILABLE**; ≥1 fresh
usable → AVAILABLE; in-gate but all stale → STALE; else DEGRADED. Absence is
never "no negative news".

### No historical-news backtest (§8)

Historical availability is never fabricated; there is no historical-news
backtest path. News + Claude are for real-time forward/paper validation only.

## Claude analyst (`app/ai/`)

* `config.py` — `AI_ANALYST_VERSION`, `PROMPT_VERSION="analyst-v1"`; `ModelClass`
  (HAIKU/SONNET/OPUS); `AIConfig` resolves `model_class → exact model_id` from
  versioned config (Sonnet-class analyst, §6), plus `analyst_enabled`,
  `timeout_seconds`, `uncertain_policy="hold"`. Model IDs are config-driven, never
  hardcoded in logic (§0.1-2); the resolved id is recorded on every verdict (§16).
* `models.py` — `AnalystDecision` (APPROVE/VETO/UNCERTAIN); `AnalystAction`
  (PROCEED/HOLD); `ReasonCode` (§6 enum); `EventRisk`; `AnalystFailure`;
  `AnalystVerdict` (audit-complete).
* `provider.py` / `fixture_provider.py` — `AnalystProvider` ABC (returns raw JSON
  text; infra → `AIUnavailableError`/`AITimeoutError`) + offline
  `FixtureAnalystProvider`. The provider is the only place a real Anthropic call
  is added later; credentials (if ever) are injected at construction, never in
  `analyze` and never in the prompt (§17).
* `schema.py` — strict validation of the raw response; ANY violation → `None`
  (→ HOLD). The model's self-reported identity is ignored; the authoritative
  `model_id`/`prompt_version` are stamped from config.
* `prompts.py` — versioned, pure, secret-free prompt builder.
* `analyst.py` — `ClaudeAnalyst`: the state machine.

### Analyst state machine (deterministic control flow)

| Condition | Action | failure |
|---|---|---|
| analyst disabled / provider missing / `AIUnavailableError` | HOLD | UNAVAILABLE |
| `AITimeoutError` | HOLD | TIMEOUT |
| news availability ≠ AVAILABLE (§0.1-3) | HOLD | NEWS_UNAVAILABLE |
| invalid/unparseable response (§6) | HOLD | SCHEMA_INVALID |
| valid → VETO / UNCERTAIN | HOLD | OK |
| valid → **APPROVE** | **PROCEED** | OK |

Every verdict is audit-complete: exact runtime `model_id`, `model_class`,
`prompt_version`, versions, `decision_time`, `processed_at`, latency, plus (on
success) confidence, reason_codes, affected_assets, event_risk, evidence. Claude
is strictly advisory — no credentials, no orders, no risk-limit changes; the
RiskManager (P6) is the final authority.

## Configuration (`app/config.py`)

`news_*` and `ai_*` fields, validated fail-closed (delegating to each dataclass
`__post_init__`); `Settings.news_config()` / `ai_config()` build them. The empty
`anthropic_api_key` placeholder is untouched — no credential, no live call.

## Tests

`tests/test_news_{config,normalization,availability,dedup,service}.py`,
`tests/test_ai_{config,schema,analyst,no_credentials}.py` (+ `tests/_p5_helpers.py`):
config invariants + Settings builders; five-timestamp assignment + tz-UTC;
affected-asset mapping; dedup first-seen-wins; the availability gate (usable /
future-excluded / unknown-excluded / stale / empty→UNAVAILABLE) + determinism;
strict schema validation; the full analyst state machine incl. every failure→HOLD
and audit-completeness; no-credentials/no-secret-in-prompt. Deterministic,
offline. All P0–P4 tests stay green.

## Next phase

**P6 — Risk + Paper Engine** (separate, explicitly authorized prompt). Owns the
runtime loop that assembles candidate→cost→news→analyst→**RiskManager (final
authority)**→sizing, plus the kill-switch and the audit persistence tables
(`claude_decisions`/`news`/`model_versions`/`prompt_versions`). Real
RSS/CryptoPanic HTTP, the `anthropic` SDK + live Claude calls, and API keys
remain deferred to a later explicitly-authorized step.
