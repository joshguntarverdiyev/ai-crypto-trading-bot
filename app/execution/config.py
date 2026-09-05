"""Paper-execution configuration and version tag (Phase 6).

Simulation assumptions only (P6 has no order book). ``liquidity_fill_cap`` is an
explicit configurable simulation parameter, NOT observed market liquidity (H7).
Fees reuse the P3 taker fee; lot rules reuse the P4 exchange-agnostic placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

PAPER_VERSION = "paper-v1"


@dataclass(frozen=True)
class PaperConfig:
    taker_fee_pct: float = 0.001  # from CostConfig; fees booked separately (H1)
    tick_size: Decimal = Decimal("0.01")
    step_size: Decimal = Decimal("0.0001")
    min_notional: Decimal = Decimal("10")
    liquidity_fill_cap: Decimal = Decimal("100000")  # simulation assumption (H7)
    starting_equity: Decimal = Decimal("10000")

    def __post_init__(self) -> None:
        if self.taker_fee_pct < 0:
            raise ValueError("taker_fee_pct must be >= 0")
        for name in ("tick_size", "step_size", "min_notional", "liquidity_fill_cap"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.starting_equity <= 0:
            raise ValueError("starting_equity must be > 0")

    @property
    def version_tag(self) -> str:
        return (
            f"{PAPER_VERSION}|fee{self.taker_fee_pct}|tick{self.tick_size}"
            f"|step{self.step_size}|mn{self.min_notional}|liq{self.liquidity_fill_cap}"
        )
