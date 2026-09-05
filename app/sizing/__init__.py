"""app.sizing — risk-budgeting position sizing (Phase 4).

Deterministic, offline, exchange-agnostic, versioned. Given a strategy candidate,
an explicit account equity (no fixed-capital assumption, §H), and caller-supplied
current exposures, compute an advisory position size subject to stop-distance +
risk budget + exchange min/max/step/tick + a conservative (non-order-book)
liquidity cap + structural portfolio caps (§13). Computed on demand; no
persistence table, no new deps, no order-book depth.

A sized ``PositionPlan`` is advisory and pre-runtime — NOT an order and NEVER a
replacement for or override of the future P6 RiskManager (final authority),
kill-switch, realized-loss/drawdown controls, or runtime portfolio state. Import
concrete types from their modules (``app.sizing.sizer.PositionSizer``, etc.);
this package exports no top-level symbols.
"""
