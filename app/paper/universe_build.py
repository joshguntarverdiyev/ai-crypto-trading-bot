"""Universe build + persistence for a paper run (Phase 9 redesign).

Ties the deterministic selection to a run: snapshot (provider) → select → optional
runtime warmup/OHLCV-quality screen (frozen P1 path) → persist the reproducible T0
universe (``paper_universe``). The final ``selection_hash`` is what gets
pre-registered. No network in the pure/offline path (provider + history probe are
injected).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.market_data.models import Symbol, Timeframe
from app.models import PaperUniverseRecord
from app.paper.config import PaperValidationConfig
from app.universe.models import UniverseSelection
from app.universe.provider import MarketUniverseProvider
from app.universe.selection import apply_history_screen, select_universe


def screen_history_via_market(
    symbols: list[Symbol],
    *,
    market_service,
    adapter,
    primary_tf: Timeframe,
    confirm_tf: Timeframe,
    warmup_min: int,
    now: datetime,
) -> dict[str, bool]:
    """Runtime warmup/OHLCV-quality probe via the FROZEN P1 path (persist=False).

    A symbol is history_ok iff BOTH timeframes return >= ``warmup_min`` usable
    completed candles and pass P1 validation. Adapter failure ⇒ not ok (fail-closed).
    """
    ok: dict[str, bool] = {}
    for symbol in symbols:
        try:
            md1 = market_service.get_candles(adapter, symbol, primary_tf, now=now)
            md4 = market_service.get_candles(adapter, symbol, confirm_tf, now=now)
        except Exception:
            ok[str(symbol)] = False
            continue
        ok[str(symbol)] = (
            md1.usable and md4.usable
            and len(md1.candles) >= warmup_min and len(md4.candles) >= warmup_min
        )
    return ok


def build_and_persist_universe(
    run_sf: sessionmaker[Session],
    run_id: str,
    *,
    provider: MarketUniverseProvider,
    cfg: PaperValidationConfig,
    now: datetime,
    history_ok: dict[str, bool] | None = None,
) -> UniverseSelection:
    """Snapshot → select → (optional history screen) → persist. Returns the final
    selection (its ``selection_hash`` is pre-registrable and fixed for the window)."""
    snapshot = provider.snapshot()
    selection = select_universe(snapshot, cfg.universe_config())
    if history_ok is not None:
        selection = apply_history_screen(selection, history_ok)

    with session_scope(run_sf) as session:
        for rank, m in enumerate(selection.ranked):
            session.add(
                PaperUniverseRecord(
                    paper_run_id=run_id,
                    selection_hash=selection.selection_hash,
                    symbol=str(m.symbol),
                    rank=rank,
                    quote_volume_24h=m.quote_volume_24h,
                    selected_at=now,
                )
            )
    return selection
