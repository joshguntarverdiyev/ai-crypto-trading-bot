"""Sentinel / news-Claude boundary (Master Plan §8, plan §21).

The pure-quant backtester must not run the news/Claude RUNTIME, must not fabricate
historical AI, and must never persist a Claude/news row. It MAY import the pure
``AnalystVerdict`` *type* (the RiskManager's signature requires it) — the sentinel
verdict is a structural placeholder with an unmistakable model_id, never stored.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from app.config import load_settings
from app.models import ClaudeDecisionRecord, NewsRecord
from backtesting.metrics import compute_metrics
from backtesting.store import persist_backtest
from tests.fixtures.backtest_data import build_dataset, run_fixture_backtest

_BACKTEST_DIR = Path(__file__).resolve().parent.parent / "backtesting"

# Runtime modules the pure-quant backtest must NEVER import.
_FORBIDDEN = (
    "app.ai.analyst",
    "app.ai.provider",
    "app.ai.fixture_provider",
    "app.ai.schema",
    "app.ai.prompts",
    "app.news.service",
    "app.news.adapter",
    "app.news.fixture_adapter",
    "app.engine",  # the operational P6 runtime
)


def _import_targets(text: str) -> list[str]:
    """Modules referenced by actual import statements (ignores docstring prose)."""
    targets: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("from "):
            targets.append(line.split()[1])
        elif line.startswith("import "):
            targets.extend(part.strip().split()[0] for part in line[len("import "):].split(","))
    return targets


def test_backtesting_does_not_import_news_or_claude_runtime() -> None:
    for path in _BACKTEST_DIR.glob("*.py"):
        targets = _import_targets(path.read_text(encoding="utf-8"))
        for forbidden in _FORBIDDEN:
            offenders = [t for t in targets if t == forbidden or t.startswith(forbidden + ".")]
            assert not offenders, f"{path.name} imports forbidden runtime {offenders!r}"


def test_only_ai_import_is_the_verdict_type() -> None:
    engine = (_BACKTEST_DIR / "engine.py").read_text(encoding="utf-8")
    # The single permitted app.ai import is the pure models module (verdict type).
    assert "from app.ai.models import" in engine
    assert "app.ai.analyst" not in engine and "app.ai.provider" not in engine


def test_sentinel_model_id_is_unmistakable_and_not_persisted(db) -> None:
    engine_db, session_factory, _url = db
    settings = load_settings(_env_file=None, environment="test")
    ds = build_dataset()
    result = run_fixture_backtest(ds, settings)
    metrics = compute_metrics(result, min_operational_trades=5)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        persist_backtest(result, metrics, session_factory=session_factory, artifacts_dir=tmp)

    with session_factory() as session:
        n_claude = session.scalar(select(func.count()).select_from(ClaudeDecisionRecord))
        n_news = session.scalar(select(func.count()).select_from(NewsRecord))
    assert n_claude == 0, "backtester must never write a claude_decisions row"
    assert n_news == 0, "backtester must never write a news row"

    # The sentinel id exists only as an in-memory structural placeholder.
    from backtesting.engine import _SENTINEL_MODEL_ID

    assert _SENTINEL_MODEL_ID == "__backtest_quant_only__"
