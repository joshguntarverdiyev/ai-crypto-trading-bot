"""Backtest determinism + reproducibility (Phase 7, plan §22/§30)."""

from __future__ import annotations

from app.config import load_settings
from tests.fixtures.backtest_data import build_dataset, run_fixture_backtest, trade_signatures


def _settings():
    return load_settings(_env_file=None, environment="test")


def test_same_dataset_twice_is_identical() -> None:
    settings = _settings()
    ds = build_dataset()
    r1 = run_fixture_backtest(ds, settings)
    r2 = run_fixture_backtest(ds, settings)
    assert trade_signatures(r1) == trade_signatures(r2)
    assert [(p.time, str(p.equity)) for p in r1.equity_curve] == [
        (p.time, str(p.equity)) for p in r2.equity_curve
    ]
    assert r1.manifest.dataset_hash == r2.manifest.dataset_hash


def test_produces_trades_and_hash_is_stable() -> None:
    settings = _settings()
    ds1 = build_dataset()
    ds2 = build_dataset()
    assert ds1.content_hash == ds2.content_hash  # deterministic dataset
    r = run_fixture_backtest(ds1, settings)
    assert len(r.trades) > 0
    assert r.manifest.engine_version == "bt-v1"
