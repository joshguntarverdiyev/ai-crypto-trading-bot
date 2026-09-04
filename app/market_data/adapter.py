"""Exchange-agnostic market-data adapter interface (Phase 1).

The core (models, validation, repository, service) depends only on this
interface. Concrete adapters own all exchange/provider-specific conversion and
never leak their types into the core. Adapters return UNTRUSTED ``RawCandle`` /
``RawTicker`` DTOs; per-candle bad values are handled as data-quality issues by
the validation layer, not as exceptions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.exceptions import UnsupportedMarketError
from app.market_data.models import RawCandle, RawTicker, Symbol, Timeframe


class ExchangeAdapter(ABC):
    """Abstract, network-free market-data source."""

    @property
    @abstractmethod
    def id(self) -> str:
        """Canonical data-origin identifier (NOT necessarily an exchange)."""

    @abstractmethod
    def supported_symbols(self) -> list[Symbol]: ...

    @abstractmethod
    def supported_timeframes(self) -> list[Timeframe]: ...

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[RawCandle]:
        """Return raw candle candidates for ``symbol``/``timeframe``.

        ``since`` is an inclusive lower bound on ``open_time``; results are
        ascending; ``limit`` caps the count. Unsupported markets raise
        :class:`UnsupportedMarketError`; a gross source/parse failure raises
        :class:`app.exceptions.AdapterError`.
        """

    @abstractmethod
    def fetch_ticker(self, symbol: Symbol) -> RawTicker: ...

    # --- shared helper ---
    def _require_supported(self, symbol: Symbol, timeframe: Timeframe | None = None) -> None:
        if symbol not in self.supported_symbols():
            raise UnsupportedMarketError(f"symbol not supported: {symbol}")
        if timeframe is not None and timeframe not in self.supported_timeframes():
            raise UnsupportedMarketError(f"timeframe not supported: {timeframe}")
