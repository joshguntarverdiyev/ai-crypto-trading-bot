"""Candle persistence repository (Phase 1).

Dialect-agnostic contract:
  * ``upsert`` is idempotent; identity is (source, symbol, timeframe, open_time).
  * same identity + same canonical values → no-op (``unchanged``).
  * same identity + different values → CONFLICT: the existing row is NEVER
    silently overwritten; a ``SystemEvent`` quality record is written and
    ``conflicts`` is incremented (first-write-wins). No reconciliation system.

The SQLite specifics are an internal implementation detail; the contract does
not depend on a particular SQL dialect function.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database import session_scope
from app.market_data.models import Candle, Symbol, Timeframe
from app.models import CandleRecord, SystemEvent
from app.time_utils import ensure_utc

_PRICE_FIELDS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class UpsertResult:
    inserted: int
    unchanged: int
    conflicts: int


def _to_record(candle: Candle) -> CandleRecord:
    return CandleRecord(
        source=candle.source,
        symbol=str(candle.symbol),
        timeframe=candle.timeframe.value,
        open_time=candle.open_time,
        close_time=candle.close_time,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
    )


def _to_domain(row: CandleRecord) -> Candle:
    return Candle(
        source=row.source,
        symbol=Symbol.parse(row.symbol),
        timeframe=Timeframe(row.timeframe),
        open_time=ensure_utc(row.open_time),
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
    )


def _diff_fields(row: CandleRecord, candle: Candle) -> list[str]:
    differing: list[str] = []
    for name in _PRICE_FIELDS:
        if getattr(row, name) != getattr(candle, name):
            differing.append(name)
    return differing


class CandleRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def upsert(self, candles: list[Candle]) -> UpsertResult:
        inserted = unchanged = conflicts = 0
        with session_scope(self._sf) as session:
            for candle in candles:
                existing = self._find(session, candle)
                if existing is None:
                    session.add(_to_record(candle))
                    inserted += 1
                    continue
                differing = _diff_fields(existing, candle)
                if not differing:
                    unchanged += 1
                else:
                    conflicts += 1
                    session.add(
                        SystemEvent(
                            level="WARNING",
                            component="market_data.repository",
                            message="candle conflict: existing row not overwritten",
                            context=json.dumps(
                                {
                                    "source": candle.source,
                                    "symbol": str(candle.symbol),
                                    "timeframe": candle.timeframe.value,
                                    "open_time": candle.open_time.isoformat(),
                                    "differing_fields": differing,
                                }
                            ),
                        )
                    )
        return UpsertResult(inserted=inserted, unchanged=unchanged, conflicts=conflicts)

    def get(
        self,
        source: str,
        symbol: Symbol,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Candle]:
        with session_scope(self._sf) as session:
            stmt = (
                select(CandleRecord)
                .where(
                    CandleRecord.source == source,
                    CandleRecord.symbol == str(symbol),
                    CandleRecord.timeframe == timeframe.value,
                )
                .order_by(CandleRecord.open_time.asc())
            )
            if start is not None:
                stmt = stmt.where(CandleRecord.open_time >= start)
            if end is not None:
                stmt = stmt.where(CandleRecord.open_time < end)
            return [_to_domain(r) for r in session.scalars(stmt).all()]

    def latest_open_time(
        self, source: str, symbol: Symbol, timeframe: Timeframe
    ) -> datetime | None:
        with session_scope(self._sf) as session:
            stmt = (
                select(CandleRecord.open_time)
                .where(
                    CandleRecord.source == source,
                    CandleRecord.symbol == str(symbol),
                    CandleRecord.timeframe == timeframe.value,
                )
                .order_by(CandleRecord.open_time.desc())
                .limit(1)
            )
            result = session.scalars(stmt).first()
            return ensure_utc(result) if result is not None else None

    def _find(self, session: Session, candle: Candle) -> CandleRecord | None:
        stmt = select(CandleRecord).where(
            CandleRecord.source == candle.source,
            CandleRecord.symbol == str(candle.symbol),
            CandleRecord.timeframe == candle.timeframe.value,
            CandleRecord.open_time == candle.open_time,
        )
        return session.scalars(stmt).first()
