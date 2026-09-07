"""ORM models package (Phase 0 foundation).

Phase 0 implements ONLY infrastructure/audit models that are genuinely used
now: ``SystemEvent``, ``ErrorRecord``, ``ConfigVersion``. The broader domain
audit schema (candles, news, sentiment, signals, claude_decisions, cost_calcs,
risk_decisions, orders, fills, fees, positions, portfolio_snapshots, pnl,
market_data_snapshots, feature_snapshots, strategy_versions, model_versions,
prompt_versions, backtest_runs, paper_trading_runs, exchange_account_snapshots)
is documented as *schema direction* in docs/architecture.md and implemented in
later phases. This avoids over-modeling while keeping the audit trail (Master
Plan §16) reconstructable.
"""

from __future__ import annotations

from app.models.backtest import BacktestRunRecord
from app.models.base import Base, TimestampMixin, UUIDMixin, VersionMixin
from app.models.candle import CandleRecord
from app.models.config_version import ConfigVersion
from app.models.decisions import ClaudeDecisionRecord, RiskDecisionRecord
from app.models.error_record import ErrorRecord
from app.models.kill_switch import KILL_SWITCH_ROW_ID, KillSwitchRecord
from app.models.news_record import NewsRecord
from app.models.paper import PaperFillRecord, PaperOrderRecord
from app.models.paper_decision import PaperDecisionRecord
from app.models.paper_run import PaperTradingRunRecord
from app.models.portfolio import PortfolioSnapshotRecord, PositionRecord
from app.models.shadow import ShadowDecisionRecord, ShadowRunRecord
from app.models.system_event import SystemEvent

__all__ = [
    "Base",
    "UUIDMixin",
    "TimestampMixin",
    "VersionMixin",
    "SystemEvent",
    "ErrorRecord",
    "ConfigVersion",
    "CandleRecord",
    # Phase 6 — persistence
    "NewsRecord",
    "ClaudeDecisionRecord",
    "RiskDecisionRecord",
    "PaperOrderRecord",
    "PaperFillRecord",
    "PositionRecord",
    "PortfolioSnapshotRecord",
    "KillSwitchRecord",
    "KILL_SWITCH_ROW_ID",
    # Phase 7 — backtest run index (research artifacts, not operational)
    "BacktestRunRecord",
    # Phase 8 — shadow-mode audit (shadow-only, not operational)
    "ShadowDecisionRecord",
    "ShadowRunRecord",
    # Phase 9 — paper-validation run catalog (main DB) + per-run decision audit (run DB)
    "PaperTradingRunRecord",
    "PaperDecisionRecord",
]
