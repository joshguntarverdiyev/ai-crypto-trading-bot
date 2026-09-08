"""Market-universe provider interface + offline fixture (Phase 9 redesign).

An additive capability (market enumeration + 24h quote volumes) that does NOT alter
the frozen P1 ``ExchangeAdapter`` ABC. The real CCXT provider is public/keyless and
lazily imported (``app/universe/ccxt_provider.py``); the fixture provider is used by
the offline test suite (no network).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.universe.models import MarketInfo


class MarketUniverseProvider(ABC):
    """Returns the exchange's current spot-market snapshot (untrusted source data)."""

    @abstractmethod
    def snapshot(self) -> list[MarketInfo]:
        """A T0 snapshot of spot markets + 24h quote volumes. Infra failure raises."""
        raise NotImplementedError


class FixtureUniverseProvider(MarketUniverseProvider):
    """Deterministic offline provider (injected markets); never touches the network."""

    def __init__(self, markets: list[MarketInfo]) -> None:
        self._markets = list(markets)

    def snapshot(self) -> list[MarketInfo]:
        return list(self._markets)
