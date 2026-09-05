"""Application exception hierarchy (Phase 0 foundation).

A small, explicit hierarchy so later phases handle errors consistently.

Domain-specific failures (market-data failure, exchange failure, Claude/AI
failure, reconciliation failure, kill-switch conditions, etc.) belong to LATER
phases and are intentionally NOT defined here. Do not add them until the phase
that implements the corresponding subsystem.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for all application errors."""


class ConfigError(AppError):
    """Configuration is missing, invalid, or unsafe. Raised at startup (fail-closed)."""


class DatabaseError(AppError):
    """Database initialization or persistence error."""


class ValidationError(AppError):
    """Domain/input validation error raised by application logic.

    (Distinct from :class:`pydantic.ValidationError`, which is a config concern
    handled in :mod:`app.config`.)
    """


class InfrastructureError(AppError):
    """Local infrastructure error (filesystem, logging, environment)."""


class InternalError(AppError):
    """Unexpected internal invariant violation. Indicates a bug."""


# --- Phase 1: market-data domain errors ---
# These are EXCEPTIONS for infrastructure/programming problems only. Per-candle
# data-quality problems (malformed values, gaps, staleness, ...) are NOT
# exceptions — they are reported via ValidationResult (see app.market_data.validation).


class MarketDataError(AppError):
    """Base class for market-data infrastructure/programming errors."""


class DataValidationError(MarketDataError):
    """Raised when a data-validation invariant is violated programmatically."""


class UnsupportedMarketError(MarketDataError):
    """Requested symbol/timeframe is not supported by the adapter."""


class AdapterError(MarketDataError):
    """The adapter could not fetch or grossly could not parse from its source."""


# --- Phase 5: news + AI-analyst domain errors ---
# EXCEPTIONS for infrastructure/programming problems only. Per-item news
# data-quality problems (missing timestamps, unknown availability, staleness,
# ...) are NOT exceptions — they are reported via the news pipeline result
# (see app.news.models / app.news.service). An unavailable/invalid Claude
# response is likewise NOT an exception raised to the caller: it maps to a
# conservative HOLD verdict (Master Plan §6 / §0.1-3).


class NewsError(AppError):
    """Base class for news infrastructure/programming errors."""


class NewsSourceError(NewsError):
    """A news source adapter could not fetch or grossly could not parse."""


class AIError(AppError):
    """Base class for AI-analyst infrastructure/programming errors."""


class AIUnavailableError(AIError):
    """The analyst provider was unavailable (never a permissive result → HOLD)."""


class AITimeoutError(AIError):
    """The analyst provider timed out (never a permissive result → HOLD)."""
