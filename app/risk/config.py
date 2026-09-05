"""RiskManager configuration and version tag (Phase 6 — source of truth).

The RiskManager is the deterministic FINAL AUTHORITY. Its limits are independent
of P4 sizing (which is advisory) and add runtime-only controls (daily/weekly
loss, drawdown, volatility shock, abnormal spread/slippage) that P4 cannot know.
Provisional, versioned — NOT calibrated (P7).
"""

from __future__ import annotations

from dataclasses import dataclass

RISK_VERSION = "risk-v1"


@dataclass(frozen=True)
class RiskConfig:
    max_risk_per_trade_pct: float = 0.01  # per-trade risk vs authoritative equity
    max_single_asset_exposure_pct: float = 0.20
    max_total_exposure_pct: float = 0.30
    max_simultaneous_positions: int = 2
    correlated_exposure_cap_pct: float = 0.30
    correlation_groups: tuple[frozenset[str], ...] = (frozenset({"BTC", "ETH"}),)
    max_daily_loss_pct: float = 0.03  # realized loss vs UTC-day baseline equity
    max_weekly_loss_pct: float = 0.06  # realized loss vs ISO-week baseline equity
    max_drawdown_pct: float = 0.15  # (HWM - equity) / HWM
    vol_shock_atr_pct: float = 0.10  # ATR% at/above this = volatility shock
    abnormal_spread_pct: float = 0.01
    abnormal_slippage_pct: float = 0.01
    max_staleness_intervals: int = 1
    plan_risk_tolerance_pct: float = 0.01  # H6: recomputed vs plan divergence bound

    def __post_init__(self) -> None:
        pcts = (
            "max_risk_per_trade_pct",
            "max_single_asset_exposure_pct",
            "max_total_exposure_pct",
            "correlated_exposure_cap_pct",
            "max_daily_loss_pct",
            "max_weekly_loss_pct",
            "max_drawdown_pct",
            "vol_shock_atr_pct",
            "abnormal_spread_pct",
            "abnormal_slippage_pct",
            "plan_risk_tolerance_pct",
        )
        for name in pcts:
            if not (0.0 < getattr(self, name) <= 1.0):
                raise ValueError(f"require 0 < {name} <= 1")
        if self.max_simultaneous_positions < 1:
            raise ValueError("max_simultaneous_positions must be >= 1")
        if self.max_staleness_intervals < 0:
            raise ValueError("max_staleness_intervals must be >= 0")

    def correlation_group_for(self, base: str) -> frozenset[str]:
        for group in self.correlation_groups:
            if base in group:
                return group
        return frozenset({base})

    @property
    def version_tag(self) -> str:
        return (
            f"{RISK_VERSION}|rpt{self.max_risk_per_trade_pct}"
            f"|sa{self.max_single_asset_exposure_pct}|tot{self.max_total_exposure_pct}"
            f"|corr{self.correlated_exposure_cap_pct}|maxp{self.max_simultaneous_positions}"
            f"|dl{self.max_daily_loss_pct}|wl{self.max_weekly_loss_pct}"
            f"|dd{self.max_drawdown_pct}|vs{self.vol_shock_atr_pct}"
            f"|as{self.abnormal_spread_pct}|asl{self.abnormal_slippage_pct}"
            f"|stale{self.max_staleness_intervals}"
        )
