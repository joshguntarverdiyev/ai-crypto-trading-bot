"""Sizing configuration and version tag (Phase 4 — source of truth).

Risk-budgeting position sizing (Master Plan §13). All values are **illustrative,
exchange-agnostic, provisional, versioned** placeholders — NOT calibrated and NOT
a committed exchange constraint (real min-notional/tick/step are resolved per
exchange at P9/P10). Percentages are decimal ratios; money is ``Decimal``.

**Contract clarification 2 (advisory, pre-runtime constraints only):** these
caps and the resulting size are deterministic offline constraints. A sized result
is NOT authorization to trade and NEVER overrides the future P6 RiskManager
(final authority), kill-switch, realized-loss/drawdown controls, or runtime
portfolio state. No order-book depth is used; the liquidity cap is a conservative
constant.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

SIZING_VERSION = "size-v1"


@dataclass(frozen=True)
class SizingConfig:
    """Provisional risk-budget + structural exposure caps (not calibrated; P7)."""

    risk_per_trade_pct: float = 0.005  # fraction of account equity risked per trade
    max_single_asset_exposure_pct: float = 0.20
    max_total_exposure_pct: float = 0.30
    max_simultaneous_positions: int = 2
    correlated_exposure_cap_pct: float = 0.30  # combined cap per correlation group
    # BTC/ETH are highly correlated (§13, ~0.7–0.9): treat as one exposure group.
    correlation_groups: tuple[frozenset[str], ...] = (frozenset({"BTC", "ETH"}),)
    min_notional: Decimal = Decimal("10")  # quote-currency minimum order notional
    step_size: Decimal = Decimal("0.0001")  # base-quantity increment
    tick_size: Decimal = Decimal("0.01")  # price increment
    liquidity_cap_quote: Decimal = Decimal("100000")  # conservative (no order book)

    def __post_init__(self) -> None:
        if not (0.0 < self.risk_per_trade_pct < 1.0):
            raise ValueError("require 0 < risk_per_trade_pct < 1")
        for name in (
            "max_single_asset_exposure_pct",
            "max_total_exposure_pct",
            "correlated_exposure_cap_pct",
        ):
            value = getattr(self, name)
            if not (0.0 < value <= 1.0):
                raise ValueError(f"require 0 < {name} <= 1")
        if self.max_simultaneous_positions < 1:
            raise ValueError("max_simultaneous_positions must be >= 1")
        for name in ("min_notional", "step_size", "tick_size", "liquidity_cap_quote"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")

    def correlation_group_for(self, base: str) -> frozenset[str]:
        """The correlation group containing ``base``; a singleton if ungrouped."""
        for group in self.correlation_groups:
            if base in group:
                return group
        return frozenset({base})

    @property
    def version_tag(self) -> str:
        return (
            f"{SIZING_VERSION}|rpt{self.risk_per_trade_pct}"
            f"|sa{self.max_single_asset_exposure_pct}|tot{self.max_total_exposure_pct}"
            f"|corr{self.correlated_exposure_cap_pct}|maxp{self.max_simultaneous_positions}"
            f"|mn{self.min_notional}|step{self.step_size}|tick{self.tick_size}"
            f"|liq{self.liquidity_cap_quote}"
        )
