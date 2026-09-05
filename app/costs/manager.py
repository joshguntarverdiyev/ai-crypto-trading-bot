"""CostManager — assembles ``min_net_edge_pct`` and runs the net-edge gate (P3).

Stateless and deterministic, like ``RegimeClassifier``. Implements the cost half
of Master Plan §4:

    min_net_edge_pct =
        entry_fee + exit_fee + spread + slippage
      + execution_uncertainty + model_uncertainty + safety_margin
      + volatility(ATR_pct) + liquidity

    trade may pass only if  expected_gross_move_pct - min_net_edge_pct > 0

The ``reward:risk`` half of §4 is deferred to P4 (needs stop distance / target).

Fail-safe (non-negotiable rule 7 / §0.1-3): unknown or non-finite inputs raise
the bar or force HOLD — never a permissive assumption. Missing spread → the
conservative fallback; missing ATR_pct → the volatility cap; any non-finite
input (or a missing expected move) → HOLD.
"""

from __future__ import annotations

import math

from app.costs.config import COST_MODEL_VERSION, CostConfig, CostScenario
from app.costs.fees import entry_exit_fee_pct
from app.costs.models import CostBreakdown, CostReason, EdgeAssessment, EdgeDecision
from app.costs.slippage import slippage_pct, volatility_pct
from app.costs.spread import resolve_spread_pct
from app.market_data.models import Ticker


class CostManager:
    def __init__(self, config: CostConfig | None = None) -> None:
        self._cfg = config or CostConfig()

    def min_net_edge(
        self,
        *,
        atr_pct: float | None,
        scenario: CostScenario = CostScenario.CONSERVATIVE,
        ticker: Ticker | None = None,
        maker_entry: bool = False,
        maker_exit: bool = False,
    ) -> CostBreakdown:
        """Compute the itemized minimum net edge for a candidate under ``scenario``.

        ``atr_pct`` must already be finite (Phase 2 guarantees this) or ``None``;
        ``None`` triggers the conservative volatility cap. Non-finite inputs are
        the caller's (``assess_edge``) responsibility to reject.
        """
        cfg = self._cfg
        entry_fee, exit_fee = entry_exit_fee_pct(
            cfg, maker_entry=maker_entry, maker_exit=maker_exit
        )
        spread, spread_estimated = resolve_spread_pct(cfg, ticker)
        slippage = slippage_pct(cfg, scenario)
        volatility = volatility_pct(cfg, atr_pct)

        components = (
            entry_fee,
            exit_fee,
            spread,
            slippage,
            cfg.execution_uncertainty_pct,
            cfg.model_uncertainty_pct,
            cfg.safety_margin_pct,
            volatility,
            cfg.liquidity_buffer_pct,
        )
        return CostBreakdown(
            entry_fee_pct=entry_fee,
            exit_fee_pct=exit_fee,
            spread_pct=spread,
            slippage_pct=slippage,
            execution_uncertainty_pct=cfg.execution_uncertainty_pct,
            model_uncertainty_pct=cfg.model_uncertainty_pct,
            safety_margin_pct=cfg.safety_margin_pct,
            volatility_pct=volatility,
            liquidity_pct=cfg.liquidity_buffer_pct,
            min_net_edge_pct=math.fsum(components),
            scenario=scenario,
            spread_estimated=spread_estimated,
            feature_missing=atr_pct is None,
            cost_model_version=COST_MODEL_VERSION,
            config_version=cfg.version_tag,
        )

    def assess_edge(
        self,
        *,
        expected_gross_move_pct: float | None,
        atr_pct: float | None,
        ticker: Ticker | None = None,
        scenario: CostScenario = CostScenario.CONSERVATIVE,
        maker_entry: bool = False,
        maker_exit: bool = False,
    ) -> EdgeAssessment:
        """Decide PASS/HOLD on the cost-side net-edge gate. Defaults to Conservative."""
        gross_ok = expected_gross_move_pct is not None and math.isfinite(
            expected_gross_move_pct
        )
        atr_bad = atr_pct is not None and not math.isfinite(atr_pct)
        # For the breakdown, a non-finite ATR_pct is treated as unavailable →
        # conservative cap (never silently used as a real value).
        atr_for_calc = atr_pct if (atr_pct is not None and math.isfinite(atr_pct)) else None

        breakdown = self.min_net_edge(
            atr_pct=atr_for_calc,
            scenario=scenario,
            ticker=ticker,
            maker_entry=maker_entry,
            maker_exit=maker_exit,
        )

        warnings: list[CostReason] = []
        if breakdown.spread_estimated:
            warnings.append(CostReason.SPREAD_ESTIMATED)
        if breakdown.feature_missing:
            warnings.append(CostReason.MISSING_FEATURE)

        # Hard fail-safe: a missing/non-finite expected move or non-finite ATR_pct
        # is never usable for a decision → HOLD.
        if not gross_ok or atr_bad:
            return EdgeAssessment(
                decision=EdgeDecision.HOLD,
                reason=CostReason.NON_FINITE,
                expected_gross_move_pct=expected_gross_move_pct if gross_ok else None,
                min_net_edge_pct=breakdown.min_net_edge_pct,
                net_edge_pct=None,
                breakdown=breakdown,
                scenario=scenario,
                warnings=tuple(warnings),
            )

        assert expected_gross_move_pct is not None  # narrowed by gross_ok
        net = expected_gross_move_pct - breakdown.min_net_edge_pct
        if net > 0.0:
            decision, reason = EdgeDecision.PASS, CostReason.OK
        else:
            decision, reason = EdgeDecision.HOLD, CostReason.BELOW_MIN_EDGE
        return EdgeAssessment(
            decision=decision,
            reason=reason,
            expected_gross_move_pct=expected_gross_move_pct,
            min_net_edge_pct=breakdown.min_net_edge_pct,
            net_edge_pct=net,
            breakdown=breakdown,
            scenario=scenario,
            warnings=tuple(warnings),
        )
