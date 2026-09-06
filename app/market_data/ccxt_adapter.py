"""Real public/keyless market-data adapter via CCXT (Phase 8 — off by default).

Implements the frozen P1 ``ExchangeAdapter`` behind which the core stays
exchange-agnostic. It uses **public** OHLCV/ticker endpoints only — constructed
with **no** API key/secret (Shadow Mode needs no trading credentials). ``ccxt`` is
imported **lazily inside methods**, so importing this module never pulls a
networking library and the offline test suite (which tests only the pure
converter) never touches the network.

The exchange id is a **data-source** choice (config), explicitly NOT the deferred
live-execution exchange (Master Plan §0.2-5 / §2). CCXT output is UNTRUSTED raw
data: the adapter only shapes it into ``RawCandle``/``RawTicker`` DTOs — the P1
``MarketDataService`` remains the sole validation authority (closed-candle,
staleness, gaps, duplicates, future-tolerance). Infra/parse/rate-limit failures
raise ``AdapterError``; the adapter NEVER turns invalid data into a valid-empty
success.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

from app.exceptions import AdapterError, UnsupportedMarketError
from app.market_data.adapter import ExchangeAdapter
from app.market_data.models import RawCandle, RawMoney, RawTicker, Symbol, Timeframe


def _num_to_raw(value: object) -> RawMoney:
    """Convert a CCXT numeric OHLCV field to a Decimal-safe raw money value.

    Floats are rendered to str (P1 rejects raw floats for money); non-finite or
    unexpected types become ``None`` so the P1 validation layer flags them.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass — reject explicitly
        return None
    if isinstance(value, (Decimal, str)):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value) if math.isfinite(value) else None
    return None


def _ts_to_datetime(ts: object) -> datetime | None:
    """CCXT candle timestamps are epoch milliseconds; accept int/float/numeric str.

    A non-numeric/None timestamp becomes ``None`` (P1 flags it as a missing field)
    — it is never silently treated as valid.
    """
    if ts is None or isinstance(ts, bool) or not isinstance(ts, (int, float, str)):
        return None
    try:
        ms = float(ts)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(ms):
        return None
    return datetime.fromtimestamp(ms / 1000.0, UTC)


def raw_candles_from_ohlcv(
    rows: object, *, source: str, symbol: str, timeframe: str
) -> list[RawCandle]:
    """Pure converter: CCXT OHLCV rows → untrusted ``RawCandle`` list.

    A malformed *shape* (not a list, or a row without the 6 OHLCV columns) is an
    ``AdapterError`` — never a valid-empty result. Per-field bad values are passed
    through for the P1 validation layer to classify.
    """
    if not isinstance(rows, (list, tuple)):
        raise AdapterError(f"malformed OHLCV payload: expected list, got {type(rows)!r}")
    out: list[RawCandle] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise AdapterError("malformed OHLCV row: expected [ts, o, h, l, c, v]")
        ts, o, h, low, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
        out.append(
            RawCandle(
                source=source,
                symbol=symbol,
                timeframe=timeframe,
                open_time=_ts_to_datetime(ts),
                open=_num_to_raw(o),
                high=_num_to_raw(h),
                low=_num_to_raw(low),
                close=_num_to_raw(c),
                volume=_num_to_raw(v),
            )
        )
    return out


class CcxtMarketDataAdapter(ExchangeAdapter):
    """Public/keyless CCXT OHLCV adapter (off by default; no trading credentials)."""

    def __init__(
        self,
        *,
        exchange_id: str,
        symbols: list[Symbol] | None = None,
        timeframes: list[Timeframe] | None = None,
        source_id: str | None = None,
        enable_rate_limit: bool = True,
    ) -> None:
        if not exchange_id:
            raise ValueError("CcxtMarketDataAdapter requires an exchange_id")
        self._exchange_id = exchange_id
        self._source_id = source_id or exchange_id
        self._symbols = symbols if symbols is not None else [
            Symbol.parse("BTC/USDT"), Symbol.parse("ETH/USDT"),
        ]
        self._timeframes = timeframes if timeframes is not None else [Timeframe.H1, Timeframe.H4]
        self._enable_rate_limit = enable_rate_limit
        self._client_obj = None  # lazily constructed

    @property
    def id(self) -> str:
        return self._source_id

    def supported_symbols(self) -> list[Symbol]:
        return list(self._symbols)

    def supported_timeframes(self) -> list[Timeframe]:
        return list(self._timeframes)

    def _client(self):  # noqa: ANN202 (ccxt exchange instance; lazy)
        if self._client_obj is None:
            try:
                import ccxt  # noqa: PLC0415 (intentional lazy import)
            except ImportError as exc:  # pragma: no cover - exercised only when extra missing
                raise AdapterError(
                    "ccxt is not installed; install the '[shadow]' extra for ccxt market data"
                ) from exc
            try:
                exchange_cls = getattr(ccxt, self._exchange_id)
            except AttributeError as exc:
                raise UnsupportedMarketError(
                    f"unknown ccxt exchange id: {self._exchange_id!r}"
                ) from exc
            # PUBLIC/keyless: no apiKey/secret is ever passed (Shadow Mode needs none).
            self._client_obj = exchange_cls({"enableRateLimit": self._enable_rate_limit})
        return self._client_obj

    def fetch_ohlcv(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[RawCandle]:
        self._require_supported(symbol, timeframe)
        since_ms = int(since.timestamp() * 1000) if since is not None else None
        try:
            rows = self._client().fetch_ohlcv(str(symbol), timeframe.value, since_ms, limit)
        except (AdapterError, UnsupportedMarketError):
            raise
        except Exception as exc:  # network/rate-limit/exchange error → AdapterError
            raise AdapterError(f"ccxt fetch_ohlcv failed: {exc}") from exc
        return raw_candles_from_ohlcv(
            rows, source=self.id, symbol=str(symbol), timeframe=timeframe.value
        )

    def fetch_ticker(self, symbol: Symbol) -> RawTicker:
        self._require_supported(symbol)
        try:
            t = self._client().fetch_ticker(str(symbol))
        except Exception as exc:
            raise AdapterError(f"ccxt fetch_ticker failed: {exc}") from exc
        ts = _ts_to_datetime(t.get("timestamp")) if isinstance(t, dict) else None
        return RawTicker(
            source=self.id, symbol=str(symbol), timestamp=ts,
            bid=_num_to_raw(t.get("bid")) if isinstance(t, dict) else None,
            ask=_num_to_raw(t.get("ask")) if isinstance(t, dict) else None,
            last=_num_to_raw(t.get("last")) if isinstance(t, dict) else None,
        )

    def server_time_utc(self) -> datetime | None:
        """Best-effort exchange server time (for clock-drift detection, §18.1)."""
        try:
            ms = self._client().milliseconds()
        except Exception:
            return None
        return _ts_to_datetime(ms)
