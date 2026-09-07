"""PaperRunner — real-time boundary scheduler + failure/idempotency policy (Phase 9).

Drives the frozen P6 ``TradingEngine`` over an EVOLVING paper account, once per
completed primary-timeframe boundary, for the canonical symbol set. Owns the
runtime the engine does not: boundary derivation, a data pre-check (that also
builds the full multi-symbol decision-time marks, OD-2), per-``(decision_time,
symbol)`` idempotency, missed-boundary gaps, the data-failure policy, clock-drift
detection, kill-state routing, the consolidated end-of-boundary snapshot, and the
run's ownership heartbeat.

Kill-state routing (§35.2/§12): RUNNING/PAUSED → ``process_tick`` (PAUSED lets
protective exits run and blocks entries); HALTED → ``run_protective_exits`` ONLY,
and only when the DB is healthy (else the exit is deferred, never fabricated). The
engine itself trips the kill switch on the same risk-reason classes as P6, so the
runner never needs to re-trip it for risk reasons.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.database import session_scope
from app.engine.pipeline import TickResult
from app.indicators.config import INDICATOR_SET_VERSION
from app.indicators.features import FeatureBuilder
from app.market_data.models import Symbol
from app.models import PaperDecisionRecord, SystemEvent
from app.paper import alerts
from app.paper.config import PaperValidationConfig
from app.paper.recorder import PaperRecorder
from app.portfolio.store import PortfolioStore
from app.regime.classifier import RegimeClassifier
from app.risk.kill_switch import KillSwitch, KillSwitchStatus
from app.strategy.config import STRATEGY_VERSION
from app.time_utils import ensure_utc, monotonic, utc_now

# Drawdown alert step (fraction): alert once per crossed bucket to limit spam.
_DRAWDOWN_ALERT_STEP = 0.05


class PaperRunner:
    def __init__(
        self,
        *,
        engine,
        recorder: PaperRecorder,
        kill_switch: KillSwitch,
        run_session_factory,
        main_session_factory,
        market_service,
        market_adapter,
        paper_config: PaperValidationConfig,
        feature_builder: FeatureBuilder,
        regime_classifier: RegimeClassifier,
        run_id: str,
        owner_token: str,
        notifier=None,
        secrets: tuple[str, ...] = (),
        heartbeat_every: int = 24,  # boundaries between liveness heartbeat alerts
    ) -> None:
        self._engine = engine
        self._rec = recorder
        self._kill = kill_switch
        self._sf = run_session_factory
        self._main_sf = main_session_factory
        self._mds = market_service
        self._adapter = market_adapter
        self._cfg = paper_config
        self._fb = feature_builder
        self._regime = regime_classifier
        self._run_id = run_id
        self._owner = owner_token
        self._notifier = notifier
        self._secrets = secrets
        self._pf = PortfolioStore(run_session_factory, paper_config.starting_equity)
        self._consecutive_failures = 0
        self._last_drawdown_bucket = 0
        self._heartbeat_every = max(1, heartbeat_every)
        self._iterations = 0
        self._lock: object | None = None  # OS run lock handle (set by build_paper_system)

    # --- helpers --------------------------------------------------------
    def _event(self, level: str, message: str, context: dict[str, object]) -> None:
        with session_scope(self._sf) as session:
            session.add(
                SystemEvent(
                    level=level, component="paper.runner", message=message,
                    context=json.dumps(context),
                )
            )

    def _alert(self, alert) -> None:
        if self._notifier is not None:
            self._notifier.send_alert(alert)

    def boundary(self, now: datetime) -> datetime:
        """Decision time = close of the most recently completed primary candle."""
        secs = self._cfg.primary_timeframe.seconds
        epoch = int(ensure_utc(now).timestamp())
        floored = (epoch // secs) * secs
        return datetime.fromtimestamp(floored, UTC)

    def _last_processed(self) -> datetime | None:
        with session_scope(self._sf) as session:
            value = session.scalars(select(func.max(PaperDecisionRecord.decision_time))).first()
            return ensure_utc(value) if value is not None else None

    def _detect_gap(self, decision_time: datetime) -> None:
        last = self._last_processed()
        if last is None:
            return
        secs = self._cfg.primary_timeframe.seconds
        gap = int((decision_time - last).total_seconds()) // secs
        if gap > 1:
            self._event(
                "WARNING", "paper.gap",
                {
                    "skipped_boundaries": gap - 1,
                    "last_processed": last.isoformat(),
                    "decision_time": decision_time.isoformat(),
                    "note": "skipped boundaries are gaps, not paper decisions",
                },
            )

    def _check_drift(self, now: datetime) -> None:
        server_time = getattr(self._adapter, "server_time_utc", None)
        if server_time is None:
            return
        try:
            svr = server_time()
        except Exception:  # best-effort; a fetch failure is handled per-boundary
            return
        if svr is None:
            return
        drift = abs((ensure_utc(svr) - ensure_utc(now)).total_seconds())
        if drift > self._cfg.clock_drift_seconds:
            self._kill.pause("clock_drift", now)
            self._event("WARNING", "paper.clock_drift",
                         {"drift_seconds": drift, "threshold": self._cfg.clock_drift_seconds})
            self._alert(alerts.paused_alert("clock_drift", at=now))

    def _heartbeat(self, now: datetime) -> None:
        from app.paper.store import heartbeat as _hb

        _hb(self._main_sf, self._run_id, owner_token=self._owner, now=now)

    # --- data pre-check + full marks + decision-time regime (OD-2/§13/§35.4) ----
    def _prefetch(
        self, decision_time: datetime
    ) -> tuple[dict[str, Decimal], dict[str, str | None], set[Symbol]]:
        """Fetch each symbol's decision-time close (for full marks), capture the
        descriptive regime available AT decision_time (for the regime-coverage gate),
        and detect hard adapter failures.

        Data-quality problems (stale/unusable) are NOT failures — the engine handles
        those as HOLD; only adapter exceptions are DATA_FAILURE. The regime is
        DESCRIPTIVE ONLY (never a trading signal) and is computed from the SAME
        decision-time candles the pipeline uses (``close_time <= decision_time``), so
        it introduces no future information and does not affect the decision."""
        marks: dict[str, Decimal] = {}
        regimes: dict[str, str | None] = {}
        failed: set[Symbol] = set()
        for symbol in self._cfg.canonical_symbols:
            try:
                md1 = self._mds.get_candles(
                    self._adapter, symbol, self._cfg.primary_timeframe, now=decision_time
                )
                md4 = self._mds.get_candles(
                    self._adapter, symbol, self._cfg.confirm_timeframe, now=decision_time
                )
            except Exception:
                failed.add(symbol)
                continue
            if md1.candles:
                marks[str(symbol)] = md1.candles[-1].close
            regimes[str(symbol)] = self._regime_label(md1, md4)
        return marks, regimes, failed

    def _regime_label(self, md1, md4) -> str | None:
        """Descriptive 'trend/volatility' label for the decision-time boundary, or
        None if features are not yet warm/available. Never affects the decision."""
        try:
            f1 = self._fb.build(md1)
            f4 = self._fb.build(md4)
            res = self._regime.classify(f1, f4)
        except Exception:
            return None
        if not res.snapshots:
            return None
        snap = res.snapshots[-1]
        return f"{snap.trend.value}/{snap.volatility.value}"

    # --- one boundary sweep --------------------------------------------
    def run_once(self, now: datetime) -> list[TickResult]:
        self._heartbeat(now)
        self._check_drift(now)
        decision_time = self.boundary(now)
        self._detect_gap(decision_time)

        marks, regimes, failed = self._prefetch(decision_time)
        processed: list[tuple[Symbol, TickResult, Decimal | None, str | None]] = []
        any_success = False
        any_failure = False

        for symbol in self._cfg.canonical_symbols:
            # Idempotency: a durable paper_decisions row short-circuits BEFORE any
            # provider call (no duplicate Claude/news cost; restart-safe).
            if self._rec.find_decision_id(decision_time, symbol) is not None:
                continue

            if symbol in failed:
                any_failure = True
                self._handle_data_failure(symbol, now)
                continue

            kill = self._kill.current()
            try:
                if kill.status is KillSwitchStatus.HALTED:
                    if not self._rec.db_healthy():
                        # Persistence unavailable: defer the protective exit; never
                        # fabricate a fill/alert; remain HALTED (§35.2).
                        self._event(
                            "CRITICAL", "paper.protective_exit_deferred",
                            {"symbol": str(symbol), "reason": "db_unavailable"},
                        )
                        continue
                    result = self._engine.run_protective_exits(
                        decision_time=decision_time, now=now, symbol=symbol, marks=marks
                    )
                else:
                    result = self._engine.process_tick(
                        decision_time=decision_time, now=now, symbol=symbol, marks=marks
                    )
            except Exception:  # persistence/unexpected: engine already HALTed; roll-back
                self._event("CRITICAL", "paper.persistence_error", {"symbol": str(symbol)})
                continue

            any_success = True
            processed.append((symbol, result, marks.get(str(symbol)), regimes.get(str(symbol))))

        if any_success and not any_failure and self._consecutive_failures > 0:
            self._consecutive_failures = 0
            self._alert(alerts.recovery_alert(at=now))

        self._finalize_boundary(decision_time, now, marks, processed)
        self._iterations += 1
        if self._iterations % self._heartbeat_every == 0:
            self._alert(alerts.heartbeat_alert(self._run_id, at=now))
        return [r for (_s, r, _m, _rg) in processed]

    def _handle_data_failure(self, symbol: Symbol, now: datetime) -> None:
        self._consecutive_failures += 1
        self._event("WARNING", "paper.data_failure",
                    {"symbol": str(symbol), "consecutive": self._consecutive_failures})
        self._alert(alerts.data_failure_alert(
            str(symbol), "adapter_error", consecutive=self._consecutive_failures, at=now))
        if self._consecutive_failures >= self._cfg.max_consecutive_data_failures:
            self._kill.pause("consecutive_data_failures", now)
            self._alert(alerts.paused_alert("consecutive_data_failures", at=now))

    def _finalize_boundary(
        self,
        decision_time: datetime,
        now: datetime,
        marks: dict[str, Decimal],
        processed: list[tuple[Symbol, TickResult, Decimal | None, str | None]],
    ) -> None:
        if not processed:
            return
        equity_after: Decimal | None = None
        exposure_after: float | None = None
        # Consolidated authoritative equity point (full marks). Skip if DB unhealthy
        # or no marks (cannot value) — the equity curve simply omits this boundary.
        if marks and self._rec.db_healthy():
            try:
                equity_after, exposure_after = self._rec.record_consolidated_snapshot(
                    marks=marks, snapshot_time=now, decision_time=decision_time
                )
            except Exception:
                self._event("WARNING", "paper.snapshot_failed",
                            {"decision_time": decision_time.isoformat()})

        for symbol, result, mark, regime in processed:
            try:
                self._rec.record_decision(
                    run_id=self._run_id, decision_time=decision_time, symbol=symbol,
                    outcome=result.outcome.value, stage=result.stage, reason=result.reason,
                    mark=mark, regime=regime, equity_after=equity_after,
                    exposure_after_pct=exposure_after,
                    indicator_set_version=INDICATOR_SET_VERSION, strategy_version=STRATEGY_VERSION,
                )
            except Exception:  # persistence failure → HALT (fail-safe, H9)
                self._kill.halt("persistence_failure", now)
                self._event("CRITICAL", "paper.decision_record_failed", {"symbol": str(symbol)})
                continue
            self._emit_outcome_alert(result, now)

        if equity_after is not None:
            self._maybe_drawdown_alert(marks, now)

    def _emit_outcome_alert(self, result: TickResult, now: datetime) -> None:
        outcome = result.outcome.value
        sym = str(result.symbol)
        if outcome == "trade":
            self._alert(alerts.entry_alert(sym, intent_id=None, at=now))
        elif outcome == "exit":
            self._alert(alerts.exit_alert(sym, result.reason, intent_id=None, at=now))
        elif outcome == "reject":
            self._alert(alerts.risk_reject_alert(sym, result.reason, at=now))

    def _maybe_drawdown_alert(self, marks: dict[str, Decimal], now: datetime) -> None:
        account = self._pf.load_account()
        equity = account.equity(marks)
        hwm = account.hwm_equity
        if hwm <= 0:
            return
        dd = float((hwm - equity) / hwm)
        bucket = int(dd / _DRAWDOWN_ALERT_STEP)
        if bucket > self._last_drawdown_bucket:
            self._last_drawdown_bucket = bucket
            self._alert(alerts.drawdown_alert(dd, at=now))
        elif bucket < self._last_drawdown_bucket:
            self._last_drawdown_bucket = bucket  # recovered; re-arm

    # --- long-running loop (offline-safe; injected clock/sleep) ---------
    def run(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] | None = None,
        max_iterations: int | None = None,
    ) -> int:
        import time as _time

        sleep_fn = sleep or _time.sleep
        iterations = 0
        while max_iterations is None or iterations < max_iterations:
            self.run_once(clock())
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            secs = self._cfg.primary_timeframe.seconds
            epoch = int(ensure_utc(clock()).timestamp())
            wait = secs - (epoch % secs)
            deadline = monotonic() + wait
            remaining = deadline - monotonic()
            if remaining > 0:
                sleep_fn(remaining)
        return iterations
