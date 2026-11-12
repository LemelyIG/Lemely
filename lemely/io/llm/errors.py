"""The client's retry vocabulary, shared by every provider."""

from __future__ import annotations

from lemely.runtime.errors import ExternalServiceError


class TransientCallError(Exception):
    """A failure the client's retry policy retries (5xx, 429, overload, connection)."""


class CapTruncatedError(ExternalServiceError):
    """A reply cut off at an output cap: billed, recorded unparsed, retried once afresh."""
