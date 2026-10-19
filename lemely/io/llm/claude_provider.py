"""Claude through the Anthropic adapter (spec 2026-10-19 §1).

Imports the Anthropic SDK (through the adapter), so ``GeminiClient`` imports this
module lazily, on the first ``claude-`` call.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import anthropic

from lemely.io.llm.errors import TransientCallError
from lemely.io.llm.provider import ProviderReply, Usage
from lemely.io.providers import ProviderError, ProviderTransientError
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from lemely.io.llm.request import LLMRequest
    from lemely.io.providers.anthropic_adapter import AnthropicAdapter


def usage_as_gemini_response(usage: Usage) -> SimpleNamespace:
    """A Claude :class:`Usage` in the ``usage_metadata`` shape ``_record_spend`` reads.

    Gemini reports candidate and thought tokens apart; Anthropic's output total
    already includes thinking, so the candidate count is the remainder.
    """
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=usage.input_tokens,
            candidates_token_count=usage.output_tokens - usage.thinking_tokens,
            thoughts_token_count=usage.thinking_tokens,
            cached_content_token_count=usage.cached_tokens,
        )
    )


class ClaudeProvider:
    """One attempt on a ``claude-`` model."""

    def __init__(self, adapter: AnthropicAdapter) -> None:
        self._adapter = adapter

    def count_tokens(self, req: LLMRequest) -> int | None:
        """Not preflighted yet (Task 2b)."""
        return None

    def complete(self, req: LLMRequest, *, log: Any) -> ProviderReply:
        """Send ``req``; 429/529/5xx/connection raise ``TransientCallError``."""
        if req.response_schema is None:
            raise ProviderError("a Claude call needs a response schema")
        t0 = time.monotonic()
        try:
            reply = self._adapter.complete(
                model=req.model,
                system_prompt=req.system,
                user_prompt=req.prompt,
                response_schema=req.response_schema,
                thinking=req.effort,
                cache_prefix=req.cache_prefix,
                images=[image.data for image in req.images],
            )
        except ProviderTransientError as exc:
            raise TransientCallError(str(exc)) from exc
        except ExternalServiceError:
            # ProviderError and friends already say what failed.
            raise
        except (anthropic.AnthropicError, OSError) as exc:
            # SDK and I/O failures only: a programming error propagates as itself.
            raise ExternalServiceError(str(exc)) from exc
        latency_ms = int((time.monotonic() - t0) * 1000)
        return ProviderReply(
            text=reply.text,
            usage_response=usage_as_gemini_response(reply.usage),
            stop_reason=reply.stop_reason,
            stop_detail=str(reply.stop_reason),
            latency_ms=latency_ms,
            usage=reply.usage,
        )
