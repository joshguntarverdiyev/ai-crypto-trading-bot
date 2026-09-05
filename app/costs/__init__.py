"""app.costs — trading-cost model and the net-edge gate (Phase 3).

Deterministic, offline, exchange-agnostic. Given a candidate's expected gross
move, decide whether a net edge survives realistic costs (Master Plan §4, §9,
§10, §14):

    fee + spread + slippage + buffers + safety_margin + volatility(ATR_pct)
        + liquidity  →  min_net_edge_pct
    expected_gross_move_pct - min_net_edge_pct > 0  →  PASS, else HOLD

Tax is NOT part of this per-trade cost model (Master Plan §0.1-1). No order-book
depth, no network, no persistence table — costs are computed on demand. Import
the concrete types from their modules (``app.costs.manager.CostManager``, etc.);
this package intentionally exports no top-level symbols.
"""
