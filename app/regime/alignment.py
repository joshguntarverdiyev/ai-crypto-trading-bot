"""Causal 1h→4h alignment with source + symbol isolation (Phase 2).

The governing 4h feature for a 1h snapshot must have the SAME ``source`` and
SAME ``symbol``, a ``close_time <= the 1h close_time`` (equality eligible; any
future 4h is not), and among eligible ones the latest ``close_time`` is chosen.
A source or symbol mismatch is never silently accepted. No resampling; no
multi-exchange merging.
"""

from __future__ import annotations

from app.indicators.models import FeatureSnapshot


def governing_4h(
    feature_1h: FeatureSnapshot, snapshots_4h: list[FeatureSnapshot]
) -> FeatureSnapshot | None:
    """Return the governing 4h snapshot for ``feature_1h``, or None."""
    t1 = feature_1h.close_time
    best: FeatureSnapshot | None = None
    for s in snapshots_4h:
        if s.source != feature_1h.source:
            continue
        if s.symbol != feature_1h.symbol:
            continue
        if s.close_time <= t1 and (best is None or s.close_time > best.close_time):
            best = s
    return best
