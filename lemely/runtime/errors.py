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


class CostCeilingError(ExternalServiceError):
    """A per-run token or USD spend ceiling was exceeded.

    Distinct from a plain :class:`ExternalServiceError` (I1 review round 2,
    MUST-FIX 1) so a caller that legitimately absorbs a transient per-call
    transport failure (e.g. the crop-and-re-read step degrading to the
    primary answer on a 503) does not also absorb a budget-ceiling breach,
    which is a stop signal for the whole run, not a per-call failure. Stays
    a subclass of ``ExternalServiceError`` so existing ``except
    ExternalServiceError`` call sites and ``assertRaisesRegex(
    ExternalServiceError, ...)`` tests keep working; a caller that must tell
    the two apart catches ``CostCeilingError`` first and re-raises it.

    Its own ``exit_code`` (I1 review round 4, SHOULD-FIX D): inheriting
    ``ExternalServiceError``'s 7 made a budget-ceiling breach and a
    transient, genuinely-retryable 503 indistinguishable to a process-level
    caller (a CI job or retry wrapper keyed on "exit 7 -> retry"), which is
    exactly the distinction this class exists to make -- a ceiling breach is
    a stop signal, retrying into it is never correct.
    """

    exit_code = 10


class PartialFailureError(LemelyError):
    """Batch completed with one or more per-item errors. exit_code stays 1."""

    exit_code = 1


class AuthError(LemelyError):
    """Authentication / authorization failure (bad credentials, OTP, token)."""

    exit_code = 8


class EmptyGradeBoundaryStoreError(LemelyError):
    """``component_thresholds`` has no verified rows.

    Raised by :class:`~lemely.io.grade_boundaries.GradeBoundaryStore` on a
    fresh or unseeded database, instead of silently grading against invented
    numbers. The remedy is always the same: run
    ``python scripts/ingest_thresholds.py``.
    """

    exit_code = 9
