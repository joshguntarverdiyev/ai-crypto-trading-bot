# Phase 1 — Market Data

The exchange-agnostic market-data foundation. No indicators, strategy, trading,
real exchange/network code, CCXT, or AI. Fully offline and deterministic.

Authoritative design: the Master Plan (`/Users/josh/.claude/plans/curious-stargazing-chipmunk.md`).

## Modules (`app/market_data/`)

* `models.py` — canonical models. `RawCandle`/`RawTicker` are **untrusted**
  adapter→validation DTOs (permissive; bad values become data-quality issues,
  not exceptions). `Candle`/`Ticker` are **strict** (tz-aware UTC enforced,
  `Decimal` money). `Symbol`, `Timeframe` (source of truth), `to_money` (rejects
  float), `utc_epoch_aligned`.
* `adapter.py` — `ExchangeAdapter` ABC (no network). Returns `RawCandle[]` /
  `RawTicker`. Unsupported markets raise `UnsupportedMarketError`; gross source
  failure raises `AdapterError`.
* `fixture_adapter.py` — `FixtureExchangeAdapter` (offline, deterministic).
* `validation.py` — `validate_candles`, `validate_ticker`, machine-consumable
  `ValidationResult` (`IssueCode`, `Severity`, `SeriesUsability`, `DataQuality`).
* `repository.py` — `CandleRepository` (idempotent, source-isolated, conflict
  detection) + `UpsertResult`.
* `service.py` — `MarketDataService` → `MarketDataResult`. The single
  consumption point for later phases.

## Key contracts

* **Candle semantics:** half-open `[open_time, close_time)`, `close_time =
  open_time + interval`, `is_closed(now) = close_time <= now`. Any candle that is
  not closed is excluded (per-candle, not just trailing) from the returned
  usable set and persistence; counted in `DataQuality.incomplete_count`.
* **Timestamps:** UTC canonical. Naive is an ERROR and rejected at the canonical
  boundary. Alignment is UTC epoch-modulo (`epoch % timeframe.seconds == 0`) —
  the canonical Phase 1 contract; future adapters normalize to it or reject.
* **Usability:** `SeriesUsability` = USABLE / INCOMPLETE (gap or stale) / INVALID
  (structural error, duplicate, out-of-order) / EMPTY. Downstream reads
  `result.usable` / `result.usability`, never logs.
* **Accounting:** `accepted_count + rejected_count == input_count`;
  `accepted_count == len(returned)`. Per-reason counters may overlap (per-candle:
  malformed/incomplete; candidate-set: duplicate/out_of_order).
* **Persistence:** identity `(source, symbol, timeframe, open_time)` — two
  sources never collide. `PreciseDecimal` guarantees exact Decimal round-trip on
  SQLite (PG precision evaluated later). Persist-eligibility ≠ usability: valid
  closed candles persist even if the series is gapped/stale.
* **Repository conflict:** same identity + same values → no-op; different values
  → conflict (existing never overwritten, `SystemEvent` recorded, first-write-wins).
* **Error boundary:** data-quality → `ValidationResult`; infra/programming
  (`UnsupportedMarketError`, `AdapterError`, `DatabaseError`) → exceptions.

## Configuration (`app/config.py`)

`market_symbols`, `market_timeframes` (validated against `Symbol`/`Timeframe`),
`max_staleness_intervals` (1), `future_tolerance_seconds` (2),
`ticker_staleness_seconds` (30).

## Tests

`tests/test_market_data_*.py` + `tests/fixtures/market_data.py`. Deterministic,
offline (network blocked), injected `now`, temp DB. All Phase 0 tests remain green.

## Next phase

**P2 — Indicators + Regime** (separate, explicitly authorized prompt). Do not
begin P2 automatically. Real network/exchange adapter (e.g. CCXT) remains
deferred behind the `ExchangeAdapter` interface.
