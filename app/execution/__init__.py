"""app.execution — paper (simulated) execution + bot-managed stops (Phase 6).

Simulated only — NO real orders, NO exchange, NO network, NO exchange-native
stops. Deterministic fills use reference + adverse directional spread + adverse
slippage (fees booked separately, H1); partial fills use a configured liquidity
simulation cap (H7). Idempotency via a client ``intent_id`` + reconcile-before-
retry (§18). Live execution and real-exchange reconciliation remain deferred
(P10/P11). Import concrete types from their modules
(``app.execution.paper_broker.PaperBroker``, etc.).
"""
