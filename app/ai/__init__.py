"""app.ai — strictly-advisory Claude analyst veto layer (Phase 5).

Deterministic control flow around a provider abstraction. Class-based model
resolution (HAIKU/SONNET/OPUS → exact runtime ``model_id`` from versioned config,
recorded for audit, Master Plan §0.1-2 / §16). The analyst emits structured
``APPROVE | VETO | UNCERTAIN``; the pipeline action is ``PROCEED`` only on a clean
APPROVE, and every failure (invalid output, provider unavailable/timeout, news
unavailable) resolves to ``HOLD`` (§6 / §0.1-3).

Claude holds no credentials, places no orders, and never overrides risk limits —
the RiskManager (P6) is the final authority. Real Anthropic SDK calls are
deferred behind ``AnalystProvider`` (offline ``FixtureAnalystProvider`` in P5; no
``anthropic`` dependency, no network, no credentials). Import concrete types from
their modules (``app.ai.analyst.ClaudeAnalyst``, etc.); this package exports no
top-level symbols.
"""
