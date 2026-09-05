"""app.engine — deterministic P4→P5→P6 tick orchestration (Phase 6).

``TradingEngine.process_tick(decision_time, now, symbol)`` runs the full pipeline
once, fail-closed at every stage, with the RiskManager as the sole gate to paper
execution. Time is injected (no uncontrolled wall-clock in business logic). A
per-tick recorder persists all audit + trade rows in one atomic transaction (H9).
No long-running daemon and no live path (deferred). Import concrete types from
their modules (``app.engine.pipeline.TradingEngine``, etc.).
"""
