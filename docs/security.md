# Security (Phase 0)

Full security architecture is in the Master Plan (§17). Phase 0 establishes the
safe-by-default foundation.

## Secrets

* No credentials in the repository. `.env` is git-ignored; `.env.example` holds
  **empty** placeholders only (no realistic-looking fake keys).
* Log redaction (`app/logging_config.py`) replaces known secret values and
  `key=value` pairs for sensitive keys before anything is written to a log.
* Do not log full configuration or environment.

## Safe defaults

* `LIVE_TRADING` defaults to `false`. In Phase 0 enabling it **fails at
  startup** (there is no execution layer). Live trading remains disabled until
  the Master Plan's live-readiness gates (P10/P11) are explicitly satisfied.
* Configuration is fail-closed: invalid values raise at startup rather than
  being silently coerced.
* Unknown financial/system state is never treated as safe (a Master Plan
  principle enforced by later phases; documented here as a standing rule).

## Claude/AI credentials (P5 interface)

The P5 analyst holds **no credentials**: `AIConfig` has no key/secret/token
field, the versioned prompt carries only market/news facts, and the
`AnalystProvider.analyze` request is secret-free (credentials, if ever needed,
are injected at provider *construction* by a later phase — never in the prompt
or request). The `anthropic_api_key` placeholder stays empty; no live Claude
call is made in P5. Claude never places orders and never overrides the
RiskManager (P6, final authority).

## Reserved for later phases (NOT in Phase 0)

Withdrawal-disabled exchange API keys, IP allow-listing, secrets manager, DB
encryption, key rotation, dependency scanning, dashboard access control, VPS
hardening, backup security, incident response. Claude/AI never holds exchange
credentials, never places orders, and never overrides the RiskManager.

## Offline guarantee

The application bootstrap and the test suite make no network requests. Tests
enforce this with a network-blocking fixture.
