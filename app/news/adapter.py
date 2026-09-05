"""News source adapter interface (Phase 5).

Mirrors the Phase 1 ``ExchangeAdapter`` boundary: an abstract source that returns
untrusted ``NewsItemRaw`` DTOs. **No network here.** A real RSS/CryptoPanic HTTP
adapter is deferred behind this interface to a later, explicitly-authorized step
(no ``requests``/``httpx`` dependency, no credentials, in Phase 5).

Infrastructure/programming failures raise ``NewsSourceError``; per-item data
quality is handled downstream (normalization), never raised here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.news.models import NewsItemRaw


class NewsSourceAdapter(ABC):
    """Abstract news source. Implementations must not perform I/O in Phase 5."""

    @abstractmethod
    def fetch(self, *, now: datetime, since: datetime | None = None) -> list[NewsItemRaw]:
        """Return raw news items known to the source as of ``now``.

        ``since`` optionally bounds how far back to return. Gross source failure
        raises :class:`app.exceptions.NewsSourceError`.
        """
        raise NotImplementedError
