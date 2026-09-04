"""Offline market-data demo (Phase 1).

Runs the full pipeline against the in-memory fixture adapter and prints the
validation/usability result. No network, no persistence. Illustrative only.

    python -m scripts.market_data_demo
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.market_data.fixture_adapter import FixtureExchangeAdapter
from app.market_data.models import RawCandle, Symbol, Timeframe
from app.market_data.service import MarketDataService

BASE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
BTC = Symbol.parse("BTC/USDT")


def _series() -> list[RawCandle]:
    return [
        RawCandle("fixture", "BTC/USDT", "1h", BASE + timedelta(hours=i),
                  Decimal("100"), Decimal("110"), Decimal("90"), Decimal("105"), Decimal("10"))
        for i in (0, 1, 3)  # note: hour 2 missing -> a gap
    ]


def main() -> None:
    adapter = FixtureExchangeAdapter(ohlcv={("BTC/USDT", "1h"): _series()})
    service = MarketDataService()
    result = service.get_candles(adapter, BTC, Timeframe.H1, now=BASE + timedelta(hours=4))
    q = result.result.quality
    print(f"usability={result.result.usability}  usable={result.usable}")
    print(
        f"accepted={q.accepted_count} rejected={q.rejected_count} "
        f"gaps={q.gap_count} stale={q.stale}"
    )
    print(f"issues={[i.code.value for i in result.result.issues]}")


if __name__ == "__main__":
    main()
