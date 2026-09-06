"""Dashboard read models (Phase 7) — READ-ONLY queries over existing tables.

Pure reads over the P6 audit tables + the P7 ``backtest_runs`` index. Returns
JSON-serializable dicts (datetimes/Decimals rendered as strings). No new read
tables; NO writes here (Master Plan §17 / plan §23).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.models import (
    KILL_SWITCH_ROW_ID,
    BacktestRunRecord,
    ClaudeDecisionRecord,
    KillSwitchRecord,
    NewsRecord,
    PaperFillRecord,
    PaperOrderRecord,
    PortfolioSnapshotRecord,
    PositionRecord,
    RiskDecisionRecord,
    ShadowDecisionRecord,
    ShadowRunRecord,
    SystemEvent,
)


def _s(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def kill_switch_state(sf: sessionmaker[Session]) -> dict[str, Any]:
    with session_scope(sf) as session:
        row = session.get(KillSwitchRecord, KILL_SWITCH_ROW_ID)
        if row is None:
            return {"status": "running", "reason": None, "tripped_at": None}
        return {"status": row.status, "reason": row.reason, "tripped_at": _s(row.tripped_at)}


def latest_portfolio(sf: sessionmaker[Session]) -> dict[str, Any] | None:
    with session_scope(sf) as session:
        row = session.scalars(
            select(PortfolioSnapshotRecord)
            .order_by(PortfolioSnapshotRecord.snapshot_time.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        return {
            "snapshot_time": _s(row.snapshot_time), "cash": _s(row.cash),
            "equity": _s(row.equity), "total_exposure": _s(row.total_exposure),
            "realized_pnl_cum": _s(row.realized_pnl_cum), "unrealized_pnl": _s(row.unrealized_pnl),
            "fees_paid_cum": _s(row.fees_paid_cum), "hwm_equity": _s(row.hwm_equity),
            "drawdown_pct": _drawdown(row.equity, row.hwm_equity),
        }


def _drawdown(equity: Decimal, hwm: Decimal) -> float:
    if hwm and hwm > 0:
        return float((hwm - equity) / hwm)
    return 0.0


def open_positions(sf: sessionmaker[Session]) -> list[dict[str, Any]]:
    with session_scope(sf) as session:
        rows = session.scalars(
            select(PositionRecord).where(PositionRecord.status == "open")
        ).all()
        return [
            {
                "symbol": r.symbol, "direction": r.direction, "quantity": _s(r.quantity),
                "average_entry": _s(r.average_entry), "stop_price": _s(r.stop_price),
                "target_price": _s(r.target_price), "opened_at": _s(r.opened_at),
                "strategy_version": r.strategy_version,
            }
            for r in rows
        ]


def recent_paper_orders(sf: sessionmaker[Session], limit: int = 50) -> list[dict[str, Any]]:
    with session_scope(sf) as session:
        rows = session.scalars(
            select(PaperOrderRecord).order_by(PaperOrderRecord.updated_at.desc()).limit(limit)
        ).all()
        return [
            {
                "symbol": r.symbol, "side": r.side, "order_type": r.order_type,
                "quantity": _s(r.quantity), "reference_price": _s(r.reference_price),
                "state": r.state, "reason": r.reason, "updated_at": _s(r.updated_at),
            }
            for r in rows
        ]


def recent_paper_fills(sf: sessionmaker[Session], limit: int = 50) -> list[dict[str, Any]]:
    with session_scope(sf) as session:
        rows = session.scalars(
            select(PaperFillRecord).order_by(PaperFillRecord.created_at.desc()).limit(limit)
        ).all()
        return [
            {
                "fill_qty": _s(r.fill_qty), "fill_price": _s(r.fill_price),
                "fee": _s(r.fee), "is_partial": r.is_partial, "created_at": _s(r.created_at),
            }
            for r in rows
        ]


def recent_risk_decisions(sf: sessionmaker[Session], limit: int = 50) -> list[dict[str, Any]]:
    with session_scope(sf) as session:
        rows = session.scalars(
            select(RiskDecisionRecord).order_by(RiskDecisionRecord.decision_time.desc()).limit(limit)
        ).all()
        return [
            {
                "decision_time": _s(r.decision_time), "symbol": r.symbol,
                "decision": r.decision, "reason": r.reason,
                "recomputed_risk_pct": r.recomputed_risk_pct,
                "exposure_after_pct": r.exposure_after_pct,
            }
            for r in rows
        ]


def recent_claude_decisions(sf: sessionmaker[Session], limit: int = 50) -> list[dict[str, Any]]:
    with session_scope(sf) as session:
        rows = session.scalars(
            select(ClaudeDecisionRecord)
            .order_by(ClaudeDecisionRecord.decision_time.desc()).limit(limit)
        ).all()
        return [
            {
                "decision_time": _s(r.decision_time), "symbol": r.symbol,
                "action": r.action, "decision": r.decision, "failure": r.failure,
                "model_id": r.model_id, "model_class": r.model_class,
                "prompt_version": r.prompt_version,
            }
            for r in rows
        ]


def recent_news(sf: sessionmaker[Session], limit: int = 50) -> list[dict[str, Any]]:
    with session_scope(sf) as session:
        rows = session.scalars(
            select(NewsRecord).order_by(NewsRecord.available_at.desc()).limit(limit)
        ).all()
        return [
            {
                "source": r.source, "title": r.title, "available_at": _s(r.available_at),
                "published_at": _s(r.published_at), "trust": r.trust,
            }
            for r in rows
        ]


def recent_system_events(sf: sessionmaker[Session], limit: int = 50) -> list[dict[str, Any]]:
    with session_scope(sf) as session:
        rows = session.scalars(
            select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(limit)
        ).all()
        return [
            {
                "level": r.level, "component": r.component, "message": r.message,
                "created_at": _s(r.created_at),
            }
            for r in rows
        ]


def recent_backtest_runs(sf: sessionmaker[Session], limit: int = 25) -> list[dict[str, Any]]:
    with session_scope(sf) as session:
        rows = session.scalars(
            select(BacktestRunRecord).order_by(BacktestRunRecord.run_time.desc()).limit(limit)
        ).all()
        return [
            {
                "id": r.id, "run_time": _s(r.run_time), "dataset_name": r.dataset_name,
                "dataset_hash": r.dataset_hash, "cost_scenario": r.cost_scenario,
                "entry_fill_rule": r.entry_fill_rule, "engine_version": r.engine_version,
                "status": r.status, "artifact_path": r.artifact_path,
            }
            for r in rows
        ]


def recent_shadow_decisions(sf: sessionmaker[Session], limit: int = 50) -> list[dict[str, Any]]:
    with session_scope(sf) as session:
        rows = session.scalars(
            select(ShadowDecisionRecord)
            .order_by(ShadowDecisionRecord.decision_time.desc()).limit(limit)
        ).all()
        return [
            {
                "decision_time": _s(r.decision_time), "symbol": r.symbol,
                "outcome": r.outcome, "stage": r.stage, "reason": r.reason,
                "regime": r.regime,
                "hyp_side": r.hyp_side, "hyp_quantity": _s(r.hyp_quantity),
                "hyp_entry_ref": _s(r.hyp_entry_ref), "hyp_fill_price": _s(r.hyp_fill_price),
                "hyp_fill_state": r.hyp_fill_state,
                "claude_decision_id": r.claude_decision_id, "risk_decision_id": r.risk_decision_id,
                "shadow_run_id": r.shadow_run_id,
                "note": "shadow decision — NOT an executed trade",
            }
            for r in rows
        ]


def recent_shadow_runs(sf: sessionmaker[Session], limit: int = 25) -> list[dict[str, Any]]:
    with session_scope(sf) as session:
        rows = session.scalars(
            select(ShadowRunRecord).order_by(ShadowRunRecord.run_time.desc()).limit(limit)
        ).all()
        return [
            {
                "id": r.id, "run_time": _s(r.run_time), "stopped_at": _s(r.stopped_at),
                "status": r.status, "market_data_source": r.market_data_source,
                "market_data_exchange_id": r.market_data_exchange_id,
                "news_source": r.news_source, "ai_provider": r.ai_provider,
                "engine_version": r.engine_version,
            }
            for r in rows
        ]


def status_overview(sf: sessionmaker[Session]) -> dict[str, Any]:
    return {
        "kill_switch": kill_switch_state(sf),
        "portfolio": latest_portfolio(sf),
        "open_positions": open_positions(sf),
        "data_freshness": {"latest_snapshot": (latest_portfolio(sf) or {}).get("snapshot_time")},
    }
