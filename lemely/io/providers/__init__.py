"""Non-Gemini model providers behind :class:`lemely.io.gemini.GeminiClient`.

``GeminiClient`` keeps the response cache, the cost ceiling, the retry policy
and the spend accounting; a provider adapter only turns one request into one
reply. Dispatch is by model-id prefix (:func:`is_anthropic_model`), so moving a
task tag to a ``claude-`` model is a settings change.

This module imports no provider SDK: ``gemini.py`` reads the prefix rule and
the error types here on every call, and the SDK loads only when a ``claude-``
model is first used.
"""

from __future__ import annotations

from lemely.runtime.errors import ExternalServiceError

ANTHROPIC_MODEL_PREFIX = "claude-"


def is_anthropic_model(model: str) -> bool:
    """True for a model id served by the Anthropic adapter (``claude-haiku-5-5``, ...)."""
    return model.startswith(ANTHROPIC_MODEL_PREFIX)


class ProviderTransientError(Exception):
    """A provider failure worth retrying: rate limit, overload, 5xx, connection, truncation.

    ``GeminiClient`` maps it onto its own ``_TransientError`` so the one retry
    policy applies to every provider.
    """


class ProviderError(ExternalServiceError):
    """A provider failure that retrying cannot fix (other 4xx, refusal, missing key)."""


__all__ = [
    "ANTHROPIC_MODEL_PREFIX",
    "ProviderError",
    "ProviderTransientError",
    "is_anthropic_model",
]
