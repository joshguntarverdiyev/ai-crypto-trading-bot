"""Offline, deterministic fixture adapter (Phase 1).

Serves pre-built ``RawCandle`` / ``RawTicker`` data with no network. Used by the
test suite and local development. Malformed data can be injected by supplying
raw candidates with bad values — the validation layer classifies them.
"""

from __future__ import annotations

from datetime import datetime

from app.exceptions import UnsupportedMarketError
from app.market_data.adapter import ExchangeAdapter
from app.market_data.models import RawCandle, RawTicker, Symbol, Timeframe


class FixtureExchangeAdapter(ExchangeAdapter):
    def __init__(
        self,
        *,
        source_id: str = "fixture",
        ohlcv: dict[tuple[str, str], list[RawCandle]] | None = None,
        tickers: dict[str, RawTicker] | None = None,
        symbols: list[Symbol] | None = None,
        timeframes: list[Timeframe] | None = None,
    ) -> None:
        self._id = source_id
        self._ohlcv = ohlcv or {}
        self._tickers = tickers or {}
        self._symbols = symbols if symbols is not None else [
            Symbol.parse("BTC/USDT"),
            Symbol.parse("ETH/USDT"),
        ]
        self._timeframes = timeframes if timeframes is not None else [Timeframe.H1, Timeframe.H4]

    @property
    def id(self) -> str:
        return self._id

    def supported_symbols(self) -> list[Symbol]:
        return list(self._symbols)

    def supported_timeframes(self) -> list[Timeframe]:
        return list(self._timeframes)

    def fetch_ohlcv(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[RawCandle]:
        self._require_supported(symbol, timeframe)
        candles = list(self._ohlcv.get((str(symbol), timeframe.value), []))
        if since is not None:
            candles = [
                c for c in candles if c.open_time is None or c.open_time >= since
            ]
        if limit is not None:
            candles = candles[:limit]
        return candles

    def fetch_ticker(self, symbol: Symbol) -> RawTicker:
        self._require_supported(symbol)
        ticker = self._tickers.get(str(symbol))
        if ticker is None:
            raise UnsupportedMarketError(f"no ticker fixture for {symbol}")
        return ticker
