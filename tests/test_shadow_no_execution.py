"""Phase 8 zero-execution invariant tests — Shadow Mode never trades (offline).

Proves that a full APPROVE → WOULD_TRADE run writes NO operational/portfolio rows
and calls NO ledger mutation — there is no reachable execution path.
"""

from __future__ import annotations

from sqlalchemy import func, select

import app.portfolio.ledger as ledger
from app.models import (
    PaperFillRecord,
    PaperOrderRecord,
    PortfolioSnapshotRecord,
    PositionRecord,
    ShadowDecisionRecord,
)
from app.shadow.models import ShadowOutcome
from tests import _p8_helpers as p8

_OPERATIONAL = (PaperOrderRecord, PaperFillRecord, PositionRecord, PortfolioSnapshotRecord)


def test_would_trade_writes_no_operational_rows_and_no_ledger_call(db, monkeypatch) -> None:
    _engine, sf, _url = db

    ledger_calls: list[str] = []
    monkeypatch.setattr(ledger, "apply_entry", lambda *a, **k: ledger_calls.append("entry"))
    monkeypatch.setattr(ledger, "apply_exit", lambda *a, **k: ledger_calls.append("exit"))
    monkeypatch.setattr(ledger, "with_hwm", lambda *a, **k: ledger_calls.append("hwm"))

    h = p8.build_shadow(sf)
    results = h.runner.run_once(p8.decision_now())

    assert results[0].outcome is ShadowOutcome.WOULD_TRADE  # a real would-be trade
    assert ledger_calls == []  # NO execution mutation ever

    with sf() as s:
        # A shadow decision exists...
        assert s.scalars(select(func.count()).select_from(ShadowDecisionRecord)).one() == 1
        # ...but ZERO operational/portfolio rows.
        for model in _OPERATIONAL:
            assert s.scalars(select(func.count()).select_from(model)).one() == 0


def test_shadow_package_never_imports_execution_path() -> None:
    # Static guard: the shadow modules do not reference ledger mutation or the P6
    # TradingEngine (defense in depth beyond the runtime spy above).
    import inspect

    import app.shadow.engine as se
    import app.shadow.recorder as sr
    import app.shadow.runner as rn

    for mod in (se, sr, rn):
        src = inspect.getsource(mod)
        # No ledger mutation call-sites and no import of the P6 execution engine.
        assert ".apply_entry(" not in src
        assert ".apply_exit(" not in src
        assert "app.engine.pipeline" not in src
        assert "import TradingEngine" not in src
        assert "TradingEngine(" not in src
