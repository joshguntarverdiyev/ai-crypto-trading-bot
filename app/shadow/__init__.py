"""Shadow Mode (Phase 8) — the real-time decision pipeline with ZERO execution.

Shadow Mode runs the *exact, unmodified* P1→P6 decision pipeline (market data →
features → regime → strategy → cost gate → news → Claude → sizing → RiskManager)
against real, current market data and records a **shadow decision** for every
processed eligible boundary. It executes **zero** real orders, changes **zero**
exchange state, and mutates **zero** portfolio/operational state.

Key invariants (Master Plan §0.1-4, §F; plan §3/§9/§15):

* No code path from Shadow Mode reaches ``ledger.apply_entry`` / the operational
  persistence tables / any execution mutation. The P6 ``TradingEngine`` is neither
  modified nor imported here.
* A **flat per-tick hypothetical account** (config starting equity, zero open
  positions) is fed to the RiskManager — no evolving book (that is P9).
* The would-be order/fill is computed with the *pure* ``PaperBroker.simulate``
  (returns a value, mutates nothing) and recorded as a HYPOTHETICAL outcome only.
* Real market-data / news / Claude adapters are OFF by default and quarantined
  behind the frozen P1/P5 interfaces; the offline test suite never exercises them.
"""

SHADOW_ENGINE_VERSION = "shadow-v1"
