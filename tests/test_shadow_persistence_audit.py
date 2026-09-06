"""Phase 8 audit-completeness + run-index tests (offline).

Every would-be trade is reconstructable (§16): candles + news + claude_decisions
(exact model_id/prompt_version) + risk_decisions + the shadow_decisions row that
links them. The shadow_runs index carries a secret-free config snapshot.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.config import load_settings
from app.exceptions import ConfigError
from app.models import (
    CandleRecord,
    ClaudeDecisionRecord,
    RiskDecisionRecord,
    ShadowDecisionRecord,
    ShadowRunRecord,
)
from app.shadow.build import build_shadow_system
from app.shadow.store import close_shadow_run, open_shadow_run
from tests import _p8_helpers as p8


def test_reconstruction_chain_present(db) -> None:
    _e, sf, _u = db
    h = p8.build_shadow(sf)
    h.runner.run_once(p8.decision_now())
    with sf() as s:
        shadow = s.scalars(select(ShadowDecisionRecord)).one()
        assert shadow.outcome == "would_trade"
        # Linked audit rows exist and are consistent.
        claude = s.get(ClaudeDecisionRecord, shadow.claude_decision_id)
        risk = s.get(RiskDecisionRecord, shadow.risk_decision_id)
        assert claude is not None and risk is not None
        assert claude.model_id and claude.prompt_version and claude.model_class
        assert risk.decision == "approve"
        # Market data was persisted (closed candles).
        assert s.scalars(select(func.count()).select_from(CandleRecord)).one() > 0
        # Feature/regime summary captured for audit.
        assert shadow.regime is not None
        assert json.loads(shadow.features_summary)


def test_open_run_snapshot_is_secret_free(db) -> None:
    _e, sf, _u = db
    settings = p8.approve_settings(
        anthropic_api_key="SECRET-KEY", telegram_bot_token="SECRET-TG",
    )
    run_id = open_shadow_run(
        sf, settings.shadow_config(), versions={"strategy_version": "strat-v1"}
    )
    close_shadow_run(sf, run_id, status="stopped")
    with sf() as s:
        row = s.get(ShadowRunRecord, run_id)
        assert row is not None and row.status == "stopped"
        blob = row.config_snapshot + row.market_data_source + row.ai_provider
        assert "SECRET-KEY" not in blob and "SECRET-TG" not in blob
        snap = json.loads(row.config_snapshot)
        assert snap["market_data_source"] == "fixture"
        assert "api_key" not in json.dumps(snap).lower()


def test_build_shadow_system_opens_run_and_is_offline(db) -> None:
    _e, sf, _u = db
    settings = p8.approve_settings()
    runner, run_id = build_shadow_system(settings, sf)
    assert run_id
    # Default fixture sources → HOLD (insufficient history), fully offline.
    results = runner.run_once(p8.decision_now())
    assert results  # produced a decision
    with sf() as s:
        assert s.get(ShadowRunRecord, run_id) is not None


def test_build_shadow_system_fail_closed_on_live_or_paper(db, tmp_path) -> None:
    _e, sf, _u = db
    # live_trading cannot even be loaded (config fail-closed), so test paper_trading.
    settings = load_settings(_env_file=None, paper_trading=True)
    with pytest.raises(ConfigError):
        build_shadow_system(settings, sf)
