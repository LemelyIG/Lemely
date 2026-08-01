"""Exception hierarchy and exit-code mapping for the Lemely CLI."""

from __future__ import annotations


class LemelyError(Exception):
    """Base class for all expected Lemely failures."""

    exit_code: int = 1


class UsageError(LemelyError):
    """Bad CLI arguments / wrong invocation."""

    exit_code = 2


class ConfigError(LemelyError):
    """Bad TOML / env / missing required setting."""

    exit_code = 3


class InputError(LemelyError):
    """Malformed user-supplied file (answers, weakness JSON, etc.)."""

    exit_code = 4


class NotFoundError(LemelyError):
    """Required file, mark scheme, or topic not found."""

    exit_code = 5


class ParseError(LemelyError):
    """PDF / JSON parse failure."""

    exit_code = 6


class ExternalServiceError(LemelyError):
    """Gemini API failure that did not recover after retry."""

    exit_code = 7


class PartialFailureError(LemelyError):
    """Batch completed with one or more per-item errors. exit_code stays 1."""

    exit_code = 1


class AuthError(LemelyError):
    """Authentication / authorization failure (bad credentials, OTP, token)."""

    exit_code = 8
