"""Deterministic multi-symbol universe selection (Phase 9 redesign).

Selects a bounded, liquid, reproducible set of Binance USDT spot pairs from a T0
market snapshot — no look-ahead, no survivorship, no calibration. The selection is
a PURE function of the recorded snapshot + versioned config; a content hash makes
it reproducible and pre-registrable. Real market enumeration (public/keyless) sits
behind ``MarketUniverseProvider`` and is off by default / lazily imported.
"""

from __future__ import annotations

UNIVERSE_VERSION = "universe-v1"
