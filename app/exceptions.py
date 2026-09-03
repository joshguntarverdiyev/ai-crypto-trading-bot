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
