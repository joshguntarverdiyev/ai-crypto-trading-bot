"""Custom SQLAlchemy column types (Phase 1).

``PreciseDecimal`` stores a ``Decimal`` as an exact fixed-point string. This
guarantees an exact Decimal round-trip on SQLite (whose NUMERIC affinity would
otherwise coerce values to float and lose precision). The contract is *exact
Decimal round-trip*; a future PostgreSQL backend may map this to ``Numeric``
with a precision/scale evaluated later against real exchange precision.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class PreciseDecimal(TypeDecorator[Decimal]):
    """Exact Decimal persistence backed by a fixed-point string column."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError("PreciseDecimal requires a Decimal value")
        # Fixed-point (non-scientific) canonical string; exact round-trip.
        return format(value, "f")

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)
