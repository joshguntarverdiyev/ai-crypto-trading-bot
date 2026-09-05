"""Kill switch — persisted RUNNING/PAUSED/HALTED state machine (Phase 6).

Fail-closed. Two trip classes: PAUSE (recoverable — auto-resume allowed under
explicit safe conditions) and HALT (critical — manual reset required). The state
is persisted in an **independent session** so a HALT survives a rolled-back
per-tick trading transaction (H9), and survives process restart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.models import KILL_SWITCH_ROW_ID, KillSwitchRecord, SystemEvent


class KillSwitchStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    HALTED = "halted"


@dataclass(frozen=True)
class KillSwitchState:
    status: KillSwitchStatus
    reason: str | None
    tripped_at: datetime | None


class KillSwitch:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def _row(self, session: Session) -> KillSwitchRecord | None:
        return session.scalars(
            select(KillSwitchRecord).where(KillSwitchRecord.id == KILL_SWITCH_ROW_ID)
        ).first()

    def current(self) -> KillSwitchState:
        with session_scope(self._sf) as session:
            row = self._row(session)
            if row is None:
                return KillSwitchState(KillSwitchStatus.RUNNING, None, None)
            return KillSwitchState(
                KillSwitchStatus(row.status), row.reason, row.tripped_at
            )

    def _write(
        self, status: KillSwitchStatus, reason: str | None, at: datetime
    ) -> None:
        # Independent transaction (H9): never batched with the trading tick.
        with session_scope(self._sf) as session:
            row = self._row(session)
            if row is None:
                row = KillSwitchRecord(id=KILL_SWITCH_ROW_ID, status=status.value,
                                       reason=reason, tripped_at=at, updated_at=at)
                session.add(row)
            else:
                row.status = status.value
                row.reason = reason
                row.tripped_at = at
                row.updated_at = at
            session.add(
                SystemEvent(
                    level="CRITICAL" if status is KillSwitchStatus.HALTED else "WARNING",
                    component="risk.kill_switch",
                    message=f"kill switch -> {status.value}",
                    context=json.dumps({"reason": reason, "at": at.isoformat()}),
                )
            )

    def pause(self, reason: str, at: datetime) -> None:
        if self.current().status is KillSwitchStatus.HALTED:
            return  # HALT dominates PAUSE
        self._write(KillSwitchStatus.PAUSED, reason, at)

    def halt(self, reason: str, at: datetime) -> None:
        self._write(KillSwitchStatus.HALTED, reason, at)

    def resume(self, at: datetime) -> bool:
        """Auto-resume only from PAUSED. HALTED requires manual_reset()."""
        if self.current().status is KillSwitchStatus.PAUSED:
            self._write(KillSwitchStatus.RUNNING, None, at)
            return True
        return False

    def manual_reset(self, at: datetime) -> None:
        self._write(KillSwitchStatus.RUNNING, None, at)
