"""Shadow run-index persistence (Phase 8) — the ``shadow_runs`` table.

Opens/closes a shadow run row (distinct from P9's ``paper_trading_runs``) with a
secret-free config snapshot and every version tag (§16). It writes NO operational
tables.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.ids import new_id
from app.models import ShadowRunRecord
from app.shadow.config import ShadowConfig
from app.time_utils import utc_now


def _config_snapshot(config: ShadowConfig) -> dict[str, object]:
    """A secret-free snapshot of the shadow configuration (no credentials)."""
    return {
        "symbols": [str(s) for s in config.symbols],
        "primary_timeframe": config.primary_timeframe.value,
        "confirm_timeframe": config.confirm_timeframe.value,
        "starting_equity": str(config.starting_equity),
        "warmup_buffer_candles": config.warmup_buffer_candles,
        "max_consecutive_data_failures": config.max_consecutive_data_failures,
        "backfill_boundaries": config.backfill_boundaries,
        "clock_drift_seconds": config.clock_drift_seconds,
        "market_data_source": config.market_data_source.value,
        "market_data_exchange_id": config.market_data_exchange_id,
        "news_source": config.news_source.value,
        "ai_provider": config.ai_provider.value,
        "engine_version": config.engine_version,
        "version_tag": config.version_tag,
    }


def open_shadow_run(
    session_factory: sessionmaker[Session],
    config: ShadowConfig,
    *,
    versions: dict[str, str],
    run_id: str | None = None,
) -> str:
    """Insert a ``shadow_runs`` row (status='running'). Returns the run_id."""
    run_id = run_id or new_id()
    with session_scope(session_factory) as session:
        session.add(
            ShadowRunRecord(
                id=run_id,
                run_time=utc_now(),
                status="running",
                symbols=json.dumps([str(s) for s in config.symbols]),
                timeframes=json.dumps(
                    [config.primary_timeframe.value, config.confirm_timeframe.value]
                ),
                market_data_source=config.market_data_source.value,
                market_data_exchange_id=config.market_data_exchange_id,
                news_source=config.news_source.value,
                ai_provider=config.ai_provider.value,
                engine_version=config.engine_version,
                indicator_set_version=versions.get("indicator_set_version", ""),
                cost_model_version=versions.get("cost_model_version", ""),
                strategy_version=versions.get("strategy_version", ""),
                sizing_version=versions.get("sizing_version", ""),
                risk_version=versions.get("risk_version", ""),
                ai_analyst_version=versions.get("ai_analyst_version", ""),
                config_snapshot=json.dumps(_config_snapshot(config)),
            )
        )
    return run_id


def close_shadow_run(
    session_factory: sessionmaker[Session], run_id: str, *, status: str = "stopped"
) -> None:
    """Mark a shadow run finished (``stopped_at``/``status``)."""
    with session_scope(session_factory) as session:
        row = session.get(ShadowRunRecord, run_id)
        if row is not None:
            row.status = status
            row.stopped_at = utc_now()
