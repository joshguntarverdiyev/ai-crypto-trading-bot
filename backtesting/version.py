"""Backtest engine version tag (Phase 7).

Bumped whenever the deterministic replay semantics change, so a persisted
``backtest_runs`` row records exactly which engine produced its artifacts (§16 /
§22 reproducibility).
"""

from __future__ import annotations

BACKTEST_ENGINE_VERSION = "bt-v1"
