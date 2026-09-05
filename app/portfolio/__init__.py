"""app.portfolio — authoritative paper portfolio/account state (Phase 6).

The DB is the source of truth; the in-memory ``AccountState`` is rebuilt from
persisted positions + the latest snapshot on restart (H11). A pure ledger books
cash/PnL/fees with no double-counting (H12); positions are self-contained
(incl. stop/target, H10). Exposure reuses correlation grouping. No live-exchange
account state (deferred). Import concrete types from their modules
(``app.portfolio.store.PortfolioStore``, ``app.portfolio.ledger``, etc.).
"""
