"""Phase 9 — Paper Validation: an evolving paper-trading account over the frozen
P1→P6 decision pipeline, driven in real time and validated over a long run.

P9 is an **orchestration + audit + validation** layer around the frozen P6
``TradingEngine`` (``app/engine/pipeline.py``). Unlike P8 Shadow Mode's flat
per-boundary hypothetical account, P9 maintains a **persistent, evolving paper
portfolio** (cash, positions, realized/unrealized P&L, drawdown, HWM) that
accumulates across boundaries and survives restart.

Non-negotiable safety (final P9 plan §2/§35.15):

* NO real money, NO real orders, NO live exchange trading, NO trading/withdrawal
  credentials. ``live_trading`` and ``paper_trading`` stay fail-closed **false**;
  P9 runs ONLY when ``paper_validation_enabled`` is true.
* Per-run **database isolation** (D-ISO): each run has its own SQLite file; the
  main DB holds only the ``paper_trading_runs`` catalog.
* RiskManager remains the FINAL AUTHORITY; Claude is advisory/veto-only.
* No code path from ``app/paper`` reaches a live/exchange execution path.
"""

PAPER_ENGINE_VERSION = "paper-v1"
