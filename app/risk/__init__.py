"""app.risk — deterministic RiskManager (FINAL AUTHORITY) + kill switch (Phase 6).

Rule-based, fail-closed. The RiskManager is the sole gate to (paper) execution:
it independently recomputes risk/exposure from authoritative account state (H6)
and adds runtime-only controls (daily/weekly loss, drawdown, volatility shock,
abnormal spread/slippage) the advisory P4 sizer cannot know. Claude can never
relax a limit. The kill switch (RUNNING/PAUSED/HALTED) is persisted independently
so a HALT survives a rolled-back tick and restart (H9). Import concrete types
from their modules (``app.risk.manager.RiskManager``, etc.).
"""
