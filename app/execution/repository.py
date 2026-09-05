"""Paper order/fill persistence + idempotency (Phase 6).

``paper_orders.intent_id`` is unique. ``find_order_state`` supports
reconcile-before-retry: before creating an order for an intent, the engine checks
for an existing (terminal) order and reuses it — never a blind duplicate (§18).
Writers take the engine's session so the whole tick commits atomically (H9).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.execution.models import ExecutionResult, Intent, OrderState
from app.models import PaperFillRecord, PaperOrderRecord
from app.time_utils import utc_now


class PaperExecutionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def find_order_state(self, intent_id: str) -> OrderState | None:
        with session_scope(self._sf) as session:
            row = session.scalars(
                select(PaperOrderRecord).where(PaperOrderRecord.intent_id == intent_id)
            ).first()
            return OrderState(row.state) if row is not None else None

    def record_execution(
        self, session: Session, intent: Intent, result: ExecutionResult, *, at: datetime
    ) -> str:
        """Write the order + its fills within the caller's transaction. Returns id."""
        order = PaperOrderRecord(
            intent_id=intent.intent_id,
            decision_time=intent.decision_time,
            symbol=str(intent.symbol),
            side=intent.side.value,
            order_type=intent.order_type.value,
            quantity=intent.quantity,
            reference_price=intent.reference_price,
            state=result.state.value,
            reason=result.reason.value,
            updated_at=at or utc_now(),
        )
        session.add(order)
        session.flush()  # assign order.id for fill FKs
        for fill in result.fills:
            session.add(
                PaperFillRecord(
                    order_id=order.id,
                    fill_qty=fill.fill_qty,
                    fill_price=fill.fill_price,
                    fee=fill.fee,
                    is_partial=fill.is_partial,
                )
            )
        return order.id
