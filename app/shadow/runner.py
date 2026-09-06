"""ShadowRunner — boundary scheduler + failure/idempotency policy (Phase 8).

Owns the runtime that the P6 engine deliberately does not: deriving the decision
boundary from a completed candle, per-``(decision_time, symbol)`` idempotency,
restart-safety, missed-boundary gaps, the data-failure policy, DB-failure HALT,
clock-drift detection, and honoring/tripping the kill switch. It performs the
persistence and kill-switch mutation; the engine stays side-effect-free.

Policies (Master Plan §9/§10/§18.1; plan §10/§11):

* Boundary = the most recently COMPLETED primary-timeframe candle close;
  ``decision_time`` is derived from that close, never from wall-clock.
* Idempotency: a durable ``shadow_decisions`` row short-circuits BEFORE any
  provider call (no duplicate Claude/news cost).
* Missed boundaries (``backfill_boundaries=0``) → a ``shadow.gap`` system event,
  never a ``shadow_decisions`` row.
* Transient data failure → HOLD the boundary (no decision row) + event; N
  consecutive → PAUSE (documented divergence from P6 HALT — no book to protect).
* Persistence failure → HALT (independent session, H9). Clock drift → PAUSE.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.database import session_scope
from app.models import ShadowDecisionRecord, SystemEvent
from app.risk.kill_switch import KillSwitch
from app.risk.models import RiskReason
from app.shadow import alerts
from app.shadow.config import ShadowConfig
from app.shadow.engine import ShadowEngine
from app.shadow.models import ShadowOutcome, ShadowResult
from app.shadow.recorder import ShadowRecorder
from app.time_utils import ensure_utc, monotonic, utc_now

# Mirrors the frozen P6 engine classification (app/engine/pipeline.py).
_HALT_REASONS = frozenset(
    {RiskReason.DAILY_LOSS_LIMIT, RiskReason.WEEKLY_LOSS_LIMIT, RiskReason.DRAWDOWN_LIMIT}
)
_PAUSE_REASONS = frozenset({RiskReason.ABNORMAL_SPREAD, RiskReason.ABNORMAL_SLIPPAGE})


class ShadowRunner:
    def __init__(
        self,
        *,
        engine: ShadowEngine,
        recorder: ShadowRecorder,
        kill_switch: KillSwitch,
        session_factory,
        shadow_config: ShadowConfig,
        market_adapter=None,
        notifier=None,
        secrets: tuple[str, ...] = (),
        shadow_run_id: str | None = None,
    ) -> None:
        self._engine = engine
        self._rec = recorder
        self._kill = kill_switch
        self._sf = session_factory
        self._cfg = shadow_config
        self._adapter = market_adapter
        self._notifier = notifier
        self._secrets = secrets
        self._run_id = shadow_run_id
        self._consecutive_failures = 0

    # --- helpers --------------------------------------------------------
    def _event(self, level: str, message: str, context: dict[str, object]) -> None:
        with session_scope(self._sf) as session:
            session.add(
                SystemEvent(
                    level=level, component="shadow.runner", message=message,
                    context=json.dumps(context),
                )
            )

    def _alert(self, alert) -> None:
        if self._notifier is not None:
            self._notifier.send_alert(alert)

    def boundary(self, now: datetime) -> datetime:
        """Decision time = close of the most recently completed primary candle."""
        secs = self._cfg.primary_timeframe.seconds
        epoch = int(now.astimezone(UTC).timestamp())
        floored = (epoch // secs) * secs
        return datetime.fromtimestamp(floored, UTC)

    def _last_processed(self) -> datetime | None:
        with session_scope(self._sf) as session:
            value = session.scalars(select(func.max(ShadowDecisionRecord.decision_time))).first()
            return ensure_utc(value) if value is not None else None

    def _detect_gap(self, decision_time: datetime) -> None:
        last = self._last_processed()
        if last is None:
            return
        secs = self._cfg.primary_timeframe.seconds
        gap = int((decision_time - last).total_seconds()) // secs
        if gap > 1:  # boundaries strictly between `last` and now were skipped
            self._event(
                "WARNING", "shadow.gap",
                {
                    "skipped_boundaries": gap - 1,
                    "last_processed": last.isoformat(),
                    "decision_time": decision_time.isoformat(),
                    "backfill_boundaries": self._cfg.backfill_boundaries,
                    "note": "skipped boundaries are gaps, not shadow decisions",
                },
            )

    def _check_drift(self, now: datetime) -> None:
        server_time = getattr(self._adapter, "server_time_utc", None)
        if server_time is None:
            return
        try:
            svr = server_time()
        except Exception:  # best-effort; a fetch failure here is handled per-boundary
            return
        if svr is None:
            return
        drift = abs((svr - now).total_seconds())
        if drift > self._cfg.clock_drift_seconds:
            self._kill.pause("clock_drift", now)
            self._event("WARNING", "shadow.clock_drift",
                         {"drift_seconds": drift, "threshold": self._cfg.clock_drift_seconds})
            self._alert(alerts.paused_alert("clock_drift", at=now))

    # --- one boundary sweep --------------------------------------------
    def run_once(self, now: datetime) -> list[ShadowResult]:
        self._check_drift(now)
        decision_time = self.boundary(now)
        self._detect_gap(decision_time)
        kill_state = self._kill.current()

        results: list[ShadowResult] = []
        for symbol in self._cfg.canonical_symbols:
            # Idempotency: skip a durably-persisted boundary BEFORE any provider call.
            if self._rec.find_decision_id(decision_time, symbol) is not None:
                continue
            result = self._engine.process_boundary(
                decision_time=decision_time, now=now, symbol=symbol, kill_state=kill_state,
            )
            results.append(result)
            self._handle(result, now)
        return results

    def _handle(self, result: ShadowResult, now: datetime) -> None:
        if result.outcome is ShadowOutcome.DATA_FAILURE:
            self._consecutive_failures += 1
            self._event("WARNING", "shadow.data_failure",
                         {"symbol": str(result.symbol), "reason": result.reason,
                          "consecutive": self._consecutive_failures})
            self._alert(alerts.data_failure_alert(
                str(result.symbol), result.reason,
                consecutive=self._consecutive_failures, at=now))
            if self._consecutive_failures >= self._cfg.max_consecutive_data_failures:
                self._kill.pause("consecutive_data_failures", now)
                self._alert(alerts.paused_alert("consecutive_data_failures", at=now))
            return

        # A successful pipeline run (even a HOLD) resets the failure streak.
        self._consecutive_failures = 0

        # Persist atomically; a persistence failure → HALT (independent session, H9).
        try:
            self._rec.record(result, shadow_run_id=self._run_id)
        except Exception:
            self._kill.halt("persistence_failure", now)
            raise

        # Trip the kill switch for the same risk-reason classes as P6.
        if result.risk_assessment is not None:
            reason = result.risk_assessment.reason
            if reason in _HALT_REASONS:
                self._kill.halt(reason.value, now)
                self._alert(alerts.halted_alert(reason.value, at=now))
            elif reason in _PAUSE_REASONS:
                self._kill.pause(reason.value, now)
                self._alert(alerts.paused_alert(reason.value, at=now))

        if result.outcome is ShadowOutcome.WOULD_TRADE:
            self._alert(alerts.would_trade_alert(result, at=now))

    # --- long-running loop (offline-safe; injected clock/sleep) ---------
    def run(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] | None = None,
        max_iterations: int | None = None,
    ) -> int:
        """Run boundary sweeps until ``max_iterations`` (None → forever).

        Sleeps to the next boundary using the MONOTONIC clock (never wall-clock for
        timing). Tests pass ``max_iterations`` and an injected ``clock``/``sleep``.
        """
        import time as _time

        sleep_fn = sleep or _time.sleep
        iterations = 0
        while max_iterations is None or iterations < max_iterations:
            now = clock()
            self.run_once(now)
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            # Sleep to just after the next boundary close (monotonic-based wait).
            secs = self._cfg.primary_timeframe.seconds
            now2 = clock()
            epoch = int(now2.astimezone(UTC).timestamp())
            wait = secs - (epoch % secs)
            deadline = monotonic() + wait
            remaining = deadline - monotonic()
            if remaining > 0:
                sleep_fn(remaining)
        return iterations
