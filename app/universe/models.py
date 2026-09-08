"""Universe domain models (Phase 9 redesign)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.market_data.models import Symbol


@dataclass(frozen=True)
class MarketInfo:
    """One market as observed in the T0 snapshot (untrusted-ish source data).

    ``history_ok`` is ``None`` at snapshot time (warmup/history is a separate runtime
    probe via the frozen P1 path); the pure selector treats ``None`` as "not yet
    disqualified" and only excludes an explicit ``False``.
    """

    symbol: Symbol
    base: str
    quote: str
    active: bool  # Binance status == TRADING
    quote_volume_24h: Decimal
    is_leveraged: bool = False  # provider hint (in addition to name-pattern detection)
    history_ok: bool | None = None


@dataclass(frozen=True)
class UniverseSelection:
    """Deterministic selection result + reproducibility hash."""

    symbols: tuple[Symbol, ...]  # selected, in deterministic processing order
    selection_hash: str  # sha256 over config + ordered (symbol, volume) — pre-registrable
    ranked: tuple[MarketInfo, ...]  # the selected infos, volume-desc then symbol-asc
    excluded: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (symbol, reason)
    universe_version: str = ""
    config_version: str = ""

    @property
    def size(self) -> int:
        return len(self.symbols)
