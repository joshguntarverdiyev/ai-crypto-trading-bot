"""Deterministic universe selection (pure; Phase 9 redesign).

``select_universe(markets, config)`` applies the exclusion/liquidity filters to a T0
snapshot, ranks survivors by 24h quote volume (desc) with a symbol tie-break (asc),
takes the top ``max_symbols``, and computes a reproducible content hash. It is a
PURE function of the recorded snapshot + config — no network, no clock, no
look-ahead. History/OHLCV-quality screening is a SEPARATE runtime step (the frozen
P1 path); this module only respects an already-known ``history_ok=False``.
"""

from __future__ import annotations

import hashlib
import json

from app.universe import UNIVERSE_VERSION
from app.universe.config import UniverseConfig
from app.universe.models import MarketInfo, UniverseSelection


def _exclusion_reason(m: MarketInfo, cfg: UniverseConfig) -> str | None:
    if m.quote.upper() != cfg.quote:
        return "quote_mismatch"
    if not m.active:
        return "inactive"
    if cfg.exclude_leveraged and (m.is_leveraged or cfg.is_leveraged_base(m.base)):
        return "leveraged_token"
    if cfg.exclude_stable_bases and m.base.upper() in cfg.stable_bases:
        return "stablecoin_base"
    if m.quote_volume_24h < cfg.min_quote_volume:
        return "below_min_volume"
    if cfg.require_history and m.history_ok is False:
        return "insufficient_history"
    return None


def select_universe(
    markets: list[MarketInfo], config: UniverseConfig | None = None
) -> UniverseSelection:
    cfg = config or UniverseConfig()
    survivors: list[MarketInfo] = []
    excluded: list[tuple[str, str]] = []
    for m in markets:
        reason = _exclusion_reason(m, cfg)
        if reason is None:
            survivors.append(m)
        else:
            excluded.append((str(m.symbol), reason))

    # Deterministic order: 24h quote volume DESC, then symbol string ASC.
    survivors.sort(key=lambda m: str(m.symbol))  # stable ASC tie-break first
    survivors.sort(key=lambda m: m.quote_volume_24h, reverse=True)  # then volume DESC
    selected = survivors[: cfg.max_symbols]
    for m in survivors[cfg.max_symbols:]:
        excluded.append((str(m.symbol), "rank_over_cap"))

    payload = {
        "config": cfg.version_tag,
        "selected": [[str(m.symbol), str(m.quote_volume_24h)] for m in selected],
    }
    selection_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return UniverseSelection(
        symbols=tuple(m.symbol for m in selected),
        selection_hash=selection_hash,
        ranked=tuple(selected),
        excluded=tuple(excluded),
        universe_version=UNIVERSE_VERSION,
        config_version=cfg.version_tag,
    )


def apply_history_screen(
    selection: UniverseSelection, history_ok: dict[str, bool]
) -> UniverseSelection:
    """Drop capped-set symbols that FAILED the runtime warmup/OHLCV-quality probe
    (the frozen P1 path); NO replacement is promoted (B3). Recomputes the final hash
    over the surviving set — this final hash is what gets pre-registered."""
    survivors = [m for m in selection.ranked if history_ok.get(str(m.symbol), True)]
    dropped = [
        (str(m.symbol), "insufficient_history")
        for m in selection.ranked
        if not history_ok.get(str(m.symbol), True)
    ]
    payload = {
        "config": selection.config_version,
        "selected": [[str(m.symbol), str(m.quote_volume_24h)] for m in survivors],
        "screened": True,
    }
    final_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return UniverseSelection(
        symbols=tuple(m.symbol for m in survivors),
        selection_hash=final_hash,
        ranked=tuple(survivors),
        excluded=selection.excluded + tuple(dropped),
        universe_version=selection.universe_version,
        config_version=selection.config_version,
    )
