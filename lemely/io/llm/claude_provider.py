"""Claude through the Anthropic adapter (spec 2026-10-19 §1).

Imports the Anthropic SDK (through the adapter), so ``GeminiClient`` imports this
module lazily, on the first ``claude-`` call.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import anthropic

from lemely.io.llm import image_fit
from lemely.io.llm.errors import TransientCallError
from lemely.io.llm.provider import ProviderReply, Usage
from lemely.io.providers import ProviderError, ProviderTransientError
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from lemely.io.llm.image_fit import FittedImages
    from lemely.io.llm.request import LLMRequest
    from lemely.io.providers.anthropic_adapter import AnthropicAdapter
    from lemely.runtime.config import Settings


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


#: Preflight with the count endpoint when the estimate is within 10% of the budget.
PREFLIGHT_SHARE = 0.9


class ClaudeProvider:
    """One attempt on a ``claude-`` model."""

    def __init__(self, adapter: AnthropicAdapter, settings: Settings) -> None:
        self._adapter = adapter
        self._settings = settings

    def _fit(self, req: LLMRequest, *, inline: bool) -> FittedImages:
        g = self._settings.gemini
        return image_fit.fit(
            [image.data for image in req.images],
            byte_limit=image_fit.DEFAULT_BYTE_LIMIT if inline else None,
            token_budget=g.claude_image_token_budget,
            floor_px=g.claude_image_floor_px,
        )

    def _pages(
        self, req: LLMRequest, log: Any
    ) -> tuple[FittedImages | None, tuple[bytes, ...], tuple[str, ...]]:
        """The fit, and the inline images or Files API ids to send (Task 2c adds ids)."""
        if not req.images:
            return None, (), ()
        fitted = self._fit(req, inline=True)
        if fitted.over_byte_limit:
            raise ProviderError(
                f"{len(req.images)} pages are {fitted.base64_bytes} bytes base64-encoded at "
                f"the {fitted.long_edge} px floor; one Claude request takes at most "
                f"{image_fit.DEFAULT_BYTE_LIMIT} bytes of inline images"
            )
        return fitted, fitted.images, ()

    def count_tokens(self, req: LLMRequest) -> int | None:
        """The count endpoint's figure for ``req`` as it would be sent, or None."""
        images = self._fit(req, inline=True).images if req.images else ()
        try:
            return self._adapter.count_tokens(
                model=req.model,
                system_prompt=req.system,
                user_prompt=req.prompt,
                cache_prefix=req.cache_prefix,
                images=images,
            )
        except ExternalServiceError:
            return None

    def complete(self, req: LLMRequest, *, log: Any) -> ProviderReply:
        """Send ``req``; 429/529/5xx/connection raise ``TransientCallError``."""
        if req.response_schema is None:
            raise ProviderError("a Claude call needs a response schema")
        fitted, images, file_ids = self._pages(req, log)
        if fitted is not None:
            if fitted.over_token_budget:
                log.warning(
                    "claude_over_tier",
                    pages=len(req.images),
                    est_tokens=fitted.est_tokens,
                    long_edge=fitted.long_edge,
                    tag=req.task_tag,
                )
            budget = self._settings.gemini.claude_image_token_budget
            if fitted.est_tokens >= PREFLIGHT_SHARE * budget:
                try:
                    counted: int | None = self._adapter.count_tokens(
                        model=req.model,
                        system_prompt=req.system,
                        user_prompt=req.prompt,
                        cache_prefix=req.cache_prefix,
                        images=images,
                        image_file_ids=file_ids,
                    )
                except ExternalServiceError:
                    counted = None
                log.info(
                    "claude_token_preflight",
                    est_tokens=fitted.est_tokens,
                    counted_tokens=counted,
                    tag=req.task_tag,
                )
        t0 = time.monotonic()
        try:
            reply = self._adapter.complete(
                model=req.model,
                system_prompt=req.system,
                user_prompt=req.prompt,
                response_schema=req.response_schema,
                thinking=req.effort,
                cache_prefix=req.cache_prefix,
                images=images,
                image_file_ids=file_ids,
                max_tokens=req.max_output_tokens,
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
