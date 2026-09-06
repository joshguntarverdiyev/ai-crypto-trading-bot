"""Cost-scenario selection helpers for the backtest (Phase 7).

These are thin adapters over the P3 cost contract — there is **no new cost math**
here. Spread/slippage for both the candidate gate (inside the strategy generator)
and the fill (PaperBroker) are resolved from the SAME ``CostConfig`` under the
active scenario, exactly as the production engine's ``_market`` does. P3
``min_net_edge`` buffers are a pre-trade decision bar and are **never** applied
again at fill time (no double counting, plan §12).
"""

from __future__ import annotations

from app.costs.config import CostConfig, CostScenario
from app.costs.slippage import slippage_pct as _p3_slippage_pct


def scenario_market_costs(
    cost_config: CostConfig, scenario: CostScenario
) -> tuple[float, float]:
    """Return ``(spread_pct, slippage_pct)`` for a scenario, mirroring the engine.

    Spread uses the conservative fallback (no order book in P0–8, §9); slippage is
    the P3 scenario-scaled execution friction. No new assumptions are introduced.
    """
    spread_pct = cost_config.spread_fallback_pct
    slippage = _p3_slippage_pct(cost_config, scenario)
    return spread_pct, slippage
