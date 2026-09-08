"""Universe-selection configuration (Phase 9 redesign — source of truth).

Deterministic, pre-registered. No correlation estimation (forbidden): cross-asset
risk is governed by the RiskManager's per-symbol + total exposure caps, documented
as a known limitation. Thresholds are provisional config, NOT calibrated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.universe import UNIVERSE_VERSION

# Base assets that are themselves stable/pegged — a "<stable>/USDT" pair is excluded
# (stablecoin-vs-stablecoin / non-directional). Deterministic, conservative list.
_DEFAULT_STABLE_BASES: tuple[str, ...] = (
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDD", "USDP", "GUSD", "PYUSD",
    "EUR", "EURT", "EURI", "AEUR", "FRAX", "LUSD", "USTC", "USD1", "XUSD",
)

# Substrings that mark Binance leveraged tokens (never spot-tradable for this system).
_DEFAULT_LEVERAGED_TOKENS: tuple[str, ...] = (
    "UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S", "2L", "2S", "4L", "4S",
)


@dataclass(frozen=True)
class UniverseConfig:
    quote: str = "USDT"  # prioritize USDT spot pairs
    max_symbols: int = 30  # N_max operational cap (effective = min(N_max, survivors))
    min_quote_volume: Decimal = Decimal("5000000")  # 24h quote-volume floor (USDT)
    exclude_leveraged: bool = True
    exclude_stable_bases: bool = True
    require_history: bool = True  # exclude symbols known to lack warmup/history
    stable_bases: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_STABLE_BASES)
    leveraged_tokens: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_LEVERAGED_TOKENS)

    def __post_init__(self) -> None:
        if not self.quote or not self.quote.isupper():
            raise ValueError("quote must be a non-empty UPPER currency code")
        if self.max_symbols < 1:
            raise ValueError("max_symbols must be >= 1")
        if self.min_quote_volume < 0:
            raise ValueError("min_quote_volume must be >= 0")

    def is_leveraged_base(self, base: str) -> bool:
        b = base.upper()
        return any(b.endswith(tok) and b != tok for tok in self.leveraged_tokens)

    @property
    def version_tag(self) -> str:
        return (
            f"{UNIVERSE_VERSION}|q{self.quote}|n{self.max_symbols}"
            f"|minvol{self.min_quote_volume}|lev{int(self.exclude_leveraged)}"
            f"|stable{int(self.exclude_stable_bases)}|hist{int(self.require_history)}"
        )
