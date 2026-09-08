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
from app.time_utils import ensure_utc
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
) -> tuple[list[Symbol], str, datetime]:
    """Resolve the FROZEN T0 universe for an explicit ``run_id`` — the single source
    of truth. Reads the MAIN catalog for the run's ``db_path`` (authoritative run
    resolution; never guesses a run), then reads ``paper_universe`` from that run's
    OWN DB read-only. Returns (ordered symbols by rank, selection_hash, frozen_t0),
    where ``frozen_t0`` is the authoritative persisted ``selected_at`` from the
    ORIGINAL selection (NOT any later resume/process time).

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
            data = [(r.symbol, r.selection_hash, r.selected_at) for r in rows]
    except SQLAlchemyError as exc:  # e.g. no paper_universe table → corrupt/absent
        raise PaperRunError(
            f"frozen universe unreadable for run_id={run_id} (fail-closed): {exc}"
        ) from None

    if not data:
        raise PaperRunError(
            f"no frozen universe persisted for run_id={run_id} (fail-closed; "
            "no .env/BTC-ETH fallback)."
        )
    hashes = {h for _sym, h, _t in data}
    if len(hashes) != 1:
        raise PaperRunError(
            f"inconsistent frozen-universe hash for run_id={run_id} "
            "(possible replacement) (fail-closed)."
        )
    symbols = [Symbol.parse(sym) for sym, _h, _t in data]  # ordered by rank
    frozen_t0 = ensure_utc(min(t for _s, _h, t in data))  # authoritative persisted T0
    return symbols, hashes.pop(), frozen_t0


def persist_universe(
    run_sf: sessionmaker[Session], run_id: str, selection: UniverseSelection, now: datetime
) -> None:
    """Persist THIS EXACT frozen ``selection`` into the run's own DB (``paper_universe``)
    keyed by ``run_id`` + ``selection_hash``. Does NOT re-snapshot or re-select — the
    single T0 Selection is the one persisted (single source of truth)."""
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


def select_frozen_universe(
    settings,  # noqa: ANN001 (Settings; annotated lazily to avoid an import cycle)
    cfg: PaperValidationConfig,
    *,
    now: datetime,
    provider: MarketUniverseProvider | None = None,
    market_service=None,  # noqa: ANN001
    market_adapter=None,  # noqa: ANN001
) -> UniverseSelection:
    """Perform the authoritative T0 selection EXACTLY ONCE: snapshot (universe
    provider) → deterministic select → frozen P1 history screen → apply. Returns the
    FROZEN ``UniverseSelection`` (the object to persist AND pass to
    ``build_paper_system``). Fail-closed (``PaperRunError``) on snapshot failure,
    empty eligible universe, history-screen failure, or empty-after-screen. Real
    CCXT provider/adapter are lazily built only when not injected (tests inject
    offline fixtures; no network offline)."""
    if provider is None:
        from app.universe.ccxt_provider import CcxtUniverseProvider

        provider = CcxtUniverseProvider(exchange_id=cfg.universe_exchange_id)
    try:
        snapshot = provider.snapshot()
    except Exception as exc:  # Binance public snapshot failure → fail-closed
        raise PaperRunError(f"T0 market snapshot failed (fail-closed): {exc}") from None

    selection = select_universe(snapshot, cfg.universe_config())
    if not selection.symbols:
        raise PaperRunError("empty eligible universe at T0 (fail-closed; no .env fallback).")

    if market_adapter is None:
        from app.market_data.ccxt_adapter import CcxtMarketDataAdapter

        market_adapter = CcxtMarketDataAdapter(
            exchange_id=cfg.market_data_exchange_id or cfg.universe_exchange_id,
            symbols=list(selection.symbols),
            timeframes=[cfg.primary_timeframe, cfg.confirm_timeframe],
        )
    if market_service is None:
        from app.market_data.service import MarketDataService

        market_service = MarketDataService()

    from app.indicators.config import IndicatorConfig

    warmup = cfg.warmup_min(
        settings.indicator_config().min_history if hasattr(settings, "indicator_config")
        else IndicatorConfig().min_history
    )
    history_ok = screen_history_via_market(
        list(selection.symbols), market_service=market_service, adapter=market_adapter,
        primary_tf=cfg.primary_timeframe, confirm_tf=cfg.confirm_timeframe,
        warmup_min=warmup, now=now,
    )
    frozen = apply_history_screen(selection, history_ok)
    if not frozen.symbols:
        raise PaperRunError(
            "empty universe after T0 history screen (fail-closed; no .env fallback)."
        )
    return frozen


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
    selection (its ``selection_hash`` is pre-registrable and fixed for the window).
    (Kept for existing callers; the P9 startup uses ``select_frozen_universe`` +
    ``persist_universe`` so there is exactly ONE selection.)"""
    snapshot = provider.snapshot()
    selection = select_universe(snapshot, cfg.universe_config())
    if history_ok is not None:
        selection = apply_history_screen(selection, history_ok)
    persist_universe(run_sf, run_id, selection, now)
    return selection
