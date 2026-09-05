"""Exchange fee estimation (Phase 3).

Pure, deterministic, exchange-agnostic. Fee rates come from ``CostConfig`` (the
config resolves per-exchange values later); nothing is hardcoded to a specific
exchange. Taker is the conservative default for both sides.
"""

from __future__ import annotations

from app.costs.config import CostConfig


def entry_exit_fee_pct(
    config: CostConfig, *, maker_entry: bool = False, maker_exit: bool = False
) -> tuple[float, float]:
    """Per-side entry and exit fees. Taker (higher) unless a maker fill is stated."""
    entry = config.maker_fee_pct if maker_entry else config.taker_fee_pct
    exit_ = config.maker_fee_pct if maker_exit else config.taker_fee_pct
    return entry, exit_


def round_trip_fee_pct(
    config: CostConfig, *, maker_entry: bool = False, maker_exit: bool = False
) -> float:
    """Total round-trip (entry + exit) fee percentage."""
    entry, exit_ = entry_exit_fee_pct(config, maker_entry=maker_entry, maker_exit=maker_exit)
    return entry + exit_
