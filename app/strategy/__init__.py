"""app.strategy — hypothesis-first quant candidate generation (Phase 4).

Deterministic, offline, exchange-agnostic, versioned. Turns Phase 2 features
into long-only *candidate* signals (Master Plan §3, §5): own EMA up-trend +
causal 4h confirmation + RSI pullback → ATR-based stop/target → reward:risk gate
→ Phase 3 cost gate. Computed on demand; no persistence table, no new deps.

A candidate is a *proposal* that passed the deterministic reward:risk and cost
gates — it is NOT a prediction and NOT authorization to trade. The RiskManager
(final authority), news, and AI are later phases. Import concrete types from
their modules (``app.strategy.generator.CandidateGenerator``, etc.); this package
exports no top-level symbols.
"""
