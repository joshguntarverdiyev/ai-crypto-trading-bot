"""Bid/ask spread estimation (Phase 3).

Consumes the Phase 1 canonical :class:`~app.market_data.models.Ticker` (Decimal
money). The Decimal→float conversion happens ONCE here, at the boundary, with
finite validation — mirroring ``FeatureBuilder`` (Phase 2 numeric policy).

Fail-safe (Master Plan §0.1-3): if a live spread cannot be derived, callers fall
back to the conservative configured value and flag it as estimated. An
unavailable spread is never treated as zero.
"""

from __future__ import annotations

import math

from app.costs.config import CostConfig
from app.market_data.models import Ticker


def spread_pct_from_ticker(ticker: Ticker) -> float | None:
    """Relative spread ``(ask - bid) / mid`` as a float, or ``None`` if unusable.

    Guards: values must be finite, ``mid > 0``, and ``ask >= bid``. Any failure
    returns ``None`` (caller applies the conservative fallback).
    """
    bid = float(ticker.bid)
    ask = float(ticker.ask)
    if not (math.isfinite(bid) and math.isfinite(ask)):
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0.0 or ask < bid:
        return None
    return (ask - bid) / mid


def resolve_spread_pct(config: CostConfig, ticker: Ticker | None) -> tuple[float, bool]:
    """Return ``(spread_pct, estimated)``.

    Uses the live ticker spread when available and valid; otherwise the
    conservative configured fallback, flagged ``estimated=True``.
    """
    if ticker is not None:
        live = spread_pct_from_ticker(ticker)
        if live is not None:
            return live, False
    return config.spread_fallback_pct, True
