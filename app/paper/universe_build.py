"""Universe build + persistence for a paper run (Phase 9 redesign).

Ties the deterministic selection to a run: snapshot (provider) → select → optional
runtime warmup/OHLCV-quality screen (frozen P1 path) → persist the reproducible T0
universe (``paper_universe``). The final ``selection_hash`` is what gets
pre-registered. No network in the pure/offline path (provider + history probe are
injected).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.database import make_session_factory, session_scope
from app.exceptions import PaperRunError
from app.market_data.models import Symbol, Timeframe
from app.models import PaperTradingRunRecord, PaperUniverseRecord
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


def _open_run_db_readonly(db_path: str) -> sessionmaker[Session]:
    """Open a run's OWN DB ENFORCED read-only (SQLite mode=ro) — never writes, never
    runs create_all, never recreates a missing file (D-ISO fail-closed)."""
    abspath = Path(db_path).expanduser().resolve()
    if not abspath.exists():
        raise PaperRunError(
            f"run DB missing at {db_path} — refusing to read/recreate (fail-closed)."
        )
    url = f"sqlite:///file:{abspath}?mode=ro&uri=true"
    engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    return make_session_factory(engine)


def load_frozen_universe(
    main_sf: sessionmaker[Session], run_id: str
) -> tuple[list[Symbol], str]:
    """Resolve the FROZEN T0 universe for an explicit ``run_id`` — the single source
    of truth. Reads the MAIN catalog for the run's ``db_path`` (authoritative run
    resolution; never guesses a run), then reads ``paper_universe`` from that run's
    OWN DB read-only. Returns (ordered symbols by rank, selection_hash).

    Fail-closed (raises ``PaperRunError``) on: unknown run_id, missing run DB,
    absent/empty universe table, run-identity mismatch, or an inconsistent
    selection hash (e.g. an attempted replacement). Callers MUST NOT fall back to
    ``.env``/BTC-ETH and MUST NOT make any provider call when this raises."""
    with session_scope(main_sf) as session:
        row = session.get(PaperTradingRunRecord, run_id)
        if row is None:
            raise PaperRunError(
                f"unknown paper run_id={run_id!r}: no paper_trading_runs catalog row (fail-closed)."
            )
        db_path = row.db_path

    run_sf = _open_run_db_readonly(db_path)
    try:
        with session_scope(run_sf) as session:
            # Identity is enforced by the run_id filter: rows for THIS run only. A
            # wrong/mismatched run DB simply yields no rows → fail-closed below.
            rows = session.scalars(
                select(PaperUniverseRecord)
                .where(PaperUniverseRecord.paper_run_id == run_id)
                .order_by(PaperUniverseRecord.rank)
            ).all()
            data = [(r.symbol, r.selection_hash) for r in rows]
    except SQLAlchemyError as exc:  # e.g. no paper_universe table → corrupt/absent
        raise PaperRunError(
            f"frozen universe unreadable for run_id={run_id} (fail-closed): {exc}"
        ) from None

    if not data:
        raise PaperRunError(
            f"no frozen universe persisted for run_id={run_id} (fail-closed; "
            "no .env/BTC-ETH fallback)."
        )
    hashes = {h for _sym, h in data}
    if len(hashes) != 1:
        raise PaperRunError(
            f"inconsistent frozen-universe hash for run_id={run_id} "
            "(possible replacement) (fail-closed)."
        )
    symbols = [Symbol.parse(sym) for sym, _h in data]  # ordered by rank
    return symbols, hashes.pop()


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
