"""app.news — news intelligence pipeline (Phase 5).

Deterministic, offline, versioned. Fetches untrusted items behind a
``NewsSourceAdapter`` interface (offline ``FixtureNewsAdapter``; real
RSS/CryptoPanic HTTP deferred), normalizes them into the strict five-timestamp
model (Master Plan §7), de-duplicates, and assembles an availability-gated
``NewsContext`` for a specific ``decision_time``. Absence/unknown/staleness is
conservative (§0.1-3), never "no negative news". No network, no credentials, no
persistence table (audit-complete objects; tables deferred to P6).

Historical news availability is not fabricated — there is no historical-news
backtest path (§8). Import concrete types from their modules
(``app.news.service.NewsService``, etc.); this package exports no top-level symbols.
"""
