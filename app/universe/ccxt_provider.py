"""Public/keyless CCXT market-universe provider (Phase 9 redesign — off by default).

Enumerates Binance spot markets + 24h quote volumes using PUBLIC endpoints only
(no apiKey/secret). ``ccxt`` is imported lazily; the offline test suite never
touches the network. Output is untrusted source data shaped into ``MarketInfo``;
the deterministic selection + the frozen P1 OHLCV validation remain authoritative.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.exceptions import AdapterError
from app.market_data.models import Symbol
from app.universe.models import MarketInfo
from app.universe.provider import MarketUniverseProvider


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


class CcxtUniverseProvider(MarketUniverseProvider):
    def __init__(self, *, exchange_id: str = "binance", enable_rate_limit: bool = True) -> None:
        if not exchange_id:
            raise ValueError("CcxtUniverseProvider requires an exchange_id")
        self._exchange_id = exchange_id
        self._enable_rate_limit = enable_rate_limit
        self._client_obj = None

    def _client(self):  # noqa: ANN202 (ccxt instance; lazy)
        if self._client_obj is None:
            try:
                import ccxt  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover
                raise AdapterError(
                    "ccxt is not installed; install the '[shadow]' extra for universe selection"
                ) from exc
            exchange_cls = getattr(ccxt, self._exchange_id, None)
            if exchange_cls is None:
                raise AdapterError(f"unknown ccxt exchange id: {self._exchange_id!r}")
            # PUBLIC/keyless: no apiKey/secret is ever passed.
            self._client_obj = exchange_cls({"enableRateLimit": self._enable_rate_limit})
        return self._client_obj

    def snapshot(self) -> list[MarketInfo]:
        client = self._client()
        try:
            markets = client.load_markets()
            tickers = client.fetch_tickers()
        except Exception as exc:  # network/parse/rate-limit → AdapterError (never fake-empty)
            raise AdapterError(f"ccxt universe snapshot failed: {exc}") from None

        out: list[MarketInfo] = []
        for sym, m in markets.items():
            if not isinstance(m, dict) or m.get("type") != "spot":
                continue
            base, quote = m.get("base"), m.get("quote")
            if not isinstance(base, str) or not isinstance(quote, str):
                continue
            try:
                symbol = Symbol.parse(sym)
            except ValueError:
                continue
            raw_info = m.get("info")
            info = raw_info if isinstance(raw_info, dict) else {}
            status = info.get("status")
            active = bool(m.get("active")) and (status in (None, "TRADING"))
            t = tickers.get(sym) if isinstance(tickers, dict) else None
            qv = _to_decimal(t.get("quoteVolume")) if isinstance(t, dict) else Decimal(0)
            out.append(
                MarketInfo(
                    symbol=symbol, base=base.upper(), quote=quote.upper(),
                    active=active, quote_volume_24h=qv, history_ok=None,
                )
            )
        return out
