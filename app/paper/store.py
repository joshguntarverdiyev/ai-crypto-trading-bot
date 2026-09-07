"""Phase 9 per-run database isolation + run catalog + single-writer ownership.

Per-run database isolation (D-ISO, final P9 plan §35.1/§26):

* Each run has its OWN SQLite file at ``{paper_runs_dir}/{run_id}.db`` holding all
  operational + audit state (``paper_orders``/``paper_fills``/``positions``/
  ``portfolio_snapshots``/``paper_decisions`` + shared audit + kill state). Runs
  can never contaminate one another — separate files ⇒ disjoint ``intent_id``
  namespaces, no shared positions/snapshots, no cross-run metric aggregation.
* The MAIN (``DATABASE_URL``) database holds ONLY the ``paper_trading_runs``
  catalog (metadata / ownership / lifecycle) — no operational portfolio state.

Single-writer ownership: an OS file lock (``flock``) is the live mutual-exclusion
guard; the catalog ``owner_token`` + ``heartbeat_at`` provide crash-takeover
bookkeeping. Fail-closed: a known run whose DB file is missing is NEVER silently
recreated; a run-identity mismatch refuses to start.
"""

from __future__ import annotations

import fcntl
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import init_db, make_engine, make_session_factory, session_scope
from app.exceptions import PaperRunError
from app.ids import new_id
from app.models import PaperDecisionRecord, PaperTradingRunRecord, SystemEvent
from app.paper.config import PaperValidationConfig
from app.time_utils import ensure_utc, utc_now


# --- per-run DB file resolution + tuning -------------------------------------
def run_db_path(cfg: PaperValidationConfig, run_id: str) -> Path:
    return Path(cfg.paper_runs_dir).expanduser() / f"{run_id}.db"


def run_db_url(cfg: PaperValidationConfig, run_id: str) -> str:
    return f"sqlite:///{run_db_path(cfg, run_id)}"


def _tune_sqlite(engine) -> None:
    """WAL + busy_timeout so read-only dashboard connections never block the writer."""

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _rec):  # noqa: ANN001, ANN202
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def make_run_session_factory(
    cfg: PaperValidationConfig, run_id: str, *, create: bool
) -> sessionmaker[Session]:
    """Return a session factory bound to the run's own DB file.

    ``create=True`` initializes a new run DB (schema). ``create=False`` requires the
    file to already exist (fail-closed: a known run DB is never silently recreated).
    """
    path = run_db_path(cfg, run_id)
    if not create and not path.exists():
        raise PaperRunError(
            f"run DB for run_id={run_id} is missing at {path} — refusing to recreate "
            "(fail-closed). Investigate before resuming."
        )
    engine = make_engine(run_db_url(cfg, run_id))
    _tune_sqlite(engine)
    init_db(engine)  # idempotent create_all
    return make_session_factory(engine)


# --- run-identity invariant --------------------------------------------------
def assert_run_identity(run_sf: sessionmaker[Session], run_id: str) -> None:
    """Fail-closed if the run DB carries a different run identity (§35.1)."""
    with session_scope(run_sf) as session:
        row = session.scalars(select(PaperDecisionRecord).limit(1)).first()
        if row is not None and row.paper_run_id != run_id:
            raise PaperRunError(
                f"run-identity mismatch: run DB contains paper_run_id={row.paper_run_id!r} "
                f"but was opened as run_id={run_id!r}. Refusing to proceed (fail-closed)."
            )


# --- OS file lock (live single-writer guard) --------------------------------
def acquire_run_lock(cfg: PaperValidationConfig, run_id: str):
    """Acquire an exclusive, non-blocking OS lock for the run. Returns the lock file
    handle (keep it open to hold the lock). Raises ``PaperRunError`` if another live
    process already owns the run."""
    path = run_db_path(cfg, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    handle = open(lock_path, "w")  # noqa: SIM115 (handle intentionally kept open)
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise PaperRunError(
            f"run_id={run_id} is already owned by another live process "
            f"(lock held at {lock_path})."
        ) from exc
    return handle


def release_run_lock(handle) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


# --- catalog (MAIN DB) -------------------------------------------------------
def _config_snapshot(cfg: PaperValidationConfig) -> dict[str, object]:
    """A secret-free snapshot of the P9 configuration (no credentials)."""
    return {
        "symbols": [str(s) for s in cfg.symbols],
        "primary_timeframe": cfg.primary_timeframe.value,
        "confirm_timeframe": cfg.confirm_timeframe.value,
        "starting_equity": str(cfg.starting_equity),
        "warmup_buffer_candles": cfg.warmup_buffer_candles,
        "max_consecutive_data_failures": cfg.max_consecutive_data_failures,
        "clock_drift_seconds": cfg.clock_drift_seconds,
        "news_settle_seconds": cfg.news_settle_seconds,
        "owner_stale_intervals": cfg.owner_stale_intervals,
        "market_data_source": cfg.market_data_source.value,
        "market_data_exchange_id": cfg.market_data_exchange_id,
        "news_source": cfg.news_source.value,
        "ai_provider": cfg.ai_provider.value,
        "min_operational_days": cfg.min_operational_days,
        "min_uptime_fraction": cfg.min_uptime_fraction,
        "max_unexplained_gaps": cfg.max_unexplained_gaps,
        "min_meaningful_trades": cfg.min_meaningful_trades,
        "min_trades_per_regime_cell": cfg.min_trades_per_regime_cell,
        "seed": cfg.seed,
        "engine_version": cfg.engine_version,
        "version_tag": cfg.version_tag,
    }


def open_paper_run(
    main_sf: sessionmaker[Session],
    cfg: PaperValidationConfig,
    *,
    versions: dict[str, str],
    owner_token: str,
    run_id: str | None = None,
) -> str:
    """Create a NEW run: catalog row (main DB) + an isolated run DB file. Returns run_id."""
    run_id = run_id or new_id()
    # Create the isolated run DB first (schema); catalog references its path.
    make_run_session_factory(cfg, run_id, create=True)
    now = utc_now()
    try:
        with session_scope(main_sf) as session:
            session.add(
                PaperTradingRunRecord(
                    id=run_id,
                    db_path=str(run_db_path(cfg, run_id)),
                    status="running",
                    owner_token=owner_token,
                    heartbeat_at=now,
                    run_time=now,
                    symbols=json.dumps([str(s) for s in cfg.symbols]),
                    timeframes=json.dumps(
                        [cfg.primary_timeframe.value, cfg.confirm_timeframe.value]
                    ),
                    market_data_source=cfg.market_data_source.value,
                    market_data_exchange_id=cfg.market_data_exchange_id,
                    news_source=cfg.news_source.value,
                    ai_provider=cfg.ai_provider.value,
                    starting_equity=cfg.starting_equity,
                    engine_version=cfg.engine_version,
                    indicator_set_version=versions.get("indicator_set_version", ""),
                    cost_model_version=versions.get("cost_model_version", ""),
                    strategy_version=versions.get("strategy_version", ""),
                    sizing_version=versions.get("sizing_version", ""),
                    risk_version=versions.get("risk_version", ""),
                    ai_analyst_version=versions.get("ai_analyst_version", ""),
                    config_snapshot=json.dumps(_config_snapshot(cfg)),
                )
            )
    except Exception as exc:  # catalog write failure at startup → fail closed
        raise PaperRunError(f"failed to write paper_trading_runs catalog row: {exc}") from exc
    return run_id


def _is_fresh(heartbeat_at: datetime | None, cfg: PaperValidationConfig, now: datetime) -> bool:
    if heartbeat_at is None:
        return False
    stale_after = cfg.owner_stale_intervals * cfg.primary_timeframe.seconds
    return (now - ensure_utc(heartbeat_at)).total_seconds() <= stale_after


def resume_paper_run(
    main_sf: sessionmaker[Session],
    cfg: PaperValidationConfig,
    run_id: str,
    *,
    owner_token: str,
    now: datetime | None = None,
) -> tuple[sessionmaker[Session], bool]:
    """Resume an existing run: verify catalog + run DB + ownership; claim ownership.

    Returns (run_session_factory, took_over). Fail-closed on unknown run, missing run
    DB, or a fresh heartbeat held by a *different* owner (the OS lock is the real
    live guard; this is defense-in-depth). Never recreates a missing run DB.
    """
    now = now or utc_now()
    with session_scope(main_sf) as session:
        row = session.get(PaperTradingRunRecord, run_id)
        if row is None:
            raise PaperRunError(f"unknown run_id={run_id}: no paper_trading_runs catalog row.")
        prior_owner = row.owner_token
        fresh = _is_fresh(row.heartbeat_at, cfg, now)
        if fresh and prior_owner is not None and prior_owner != owner_token:
            raise PaperRunError(
                f"run_id={run_id} has a fresh heartbeat from a different owner "
                f"({prior_owner!r}); refusing to resume (another live owner)."
            )
        took_over = bool(prior_owner is not None and prior_owner != owner_token)
        row.owner_token = owner_token
        row.heartbeat_at = now
        row.status = "running"
        row.stopped_at = None

    # Verify the isolated run DB exists (fail-closed; never recreate) + identity.
    run_sf = make_run_session_factory(cfg, run_id, create=False)
    assert_run_identity(run_sf, run_id)
    if took_over:
        with session_scope(run_sf) as s:
            s.add(
                SystemEvent(
                    level="WARNING", component="paper.store", message="paper.run_takeover",
                    context=json.dumps({"run_id": run_id, "new_owner": owner_token}),
                )
            )
    return run_sf, took_over


def heartbeat(
    main_sf: sessionmaker[Session], run_id: str, *, owner_token: str, now: datetime | None = None
) -> None:
    """Refresh the run's catalog heartbeat (only if still the owner)."""
    now = now or utc_now()
    with session_scope(main_sf) as session:
        row = session.get(PaperTradingRunRecord, run_id)
        if row is not None and row.owner_token == owner_token:
            row.heartbeat_at = now


def record_prereg_digest(main_sf: sessionmaker[Session], run_id: str, digest: str) -> None:
    """Lock the pre-registration digest for the run (before results are read)."""
    with session_scope(main_sf) as session:
        row = session.get(PaperTradingRunRecord, run_id)
        if row is not None:
            row.prereg_digest = digest


def close_paper_run(
    main_sf: sessionmaker[Session], run_id: str, *, status: str = "stopped"
) -> None:
    """Mark a run finished (``stopped_at``/``status``); releases logical ownership."""
    with session_scope(main_sf) as session:
        row = session.get(PaperTradingRunRecord, run_id)
        if row is not None:
            row.status = status
            row.stopped_at = utc_now()
            row.owner_token = None
