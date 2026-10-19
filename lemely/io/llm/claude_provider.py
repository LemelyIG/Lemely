"""Claude through the Anthropic adapter (spec 2026-10-19 §1).

Imports the Anthropic SDK (through the adapter), so ``GeminiClient`` imports this
module lazily, on the first ``claude-`` call.
"""

from __future__ import annotations

import base64
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import anthropic

from lemely.io.llm import image_fit
from lemely.io.llm.errors import TransientCallError
from lemely.io.llm.provider import ProviderReply, Usage
from lemely.io.providers import ProviderError, ProviderTransientError
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from anthropic.types import DocumentBlockParam

    from lemely.io.llm.image_fit import FittedImages
    from lemely.io.llm.request import DocumentInput, LLMRequest
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
            cache_write_5m_tokens=usage.cache_write_5m_tokens,
            cache_write_1h_tokens=usage.cache_write_1h_tokens,
            container_seconds=usage.container_seconds,
        )
    )


#: The API's request limit (PDF support docs, read 2026-10-20).
MAX_REQUEST_BYTES = 32_000_000
#: PDF pages per request: 600 when the context window is 1M tokens (Haiku 5.5, Sonnet 5.5
#: and Opus 5.5 all have 1M; models page, read 2026-10-20), 100 under 1M. The limit
#: assumes 1M-context models: every configured Claude model has one (platform.claude.com
#: models overview, checked 2026-10-19); a model under 1M would need 100.
MAX_PDF_PAGES = 600


def _pdf_pages(data: bytes, number: int) -> int:
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(data)
    except (pdfium.PdfiumError, ValueError, OSError) as exc:
        raise ProviderError(f"document {number} is not a readable PDF: {exc}") from exc
    try:
        return len(doc)
    finally:
        doc.close()


def document_blocks(docs: Sequence[DocumentInput]) -> list[DocumentBlockParam]:
    """``document`` blocks: PDFs as base64, text as plain text; page limit enforced."""
    blocks: list[DocumentBlockParam] = []
    pages = 0
    for number, doc in enumerate(docs, start=1):
        source: dict[str, Any]
        if doc.media_type == "application/pdf":
            pages += _pdf_pages(doc.data, number)
            source = {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(doc.data).decode("ascii"),
            }
        else:
            source = {"type": "text", "media_type": "text/plain", "data": doc.data.decode("utf-8")}
        block: dict[str, Any] = {"type": "document", "source": source}
        if doc.cache:
            block["cache_control"] = {"type": "ephemeral"}
        if doc.citations:
            block["citations"] = {"enabled": True}
        if doc.title:
            block["title"] = doc.title
        blocks.append(cast("DocumentBlockParam", block))
    if pages > MAX_PDF_PAGES:
        raise ProviderError(
            f"{pages} PDF pages in one Claude request; the limit is {MAX_PDF_PAGES}"
        )
    return blocks


def _request_bytes(req: LLMRequest, images: Sequence[bytes]) -> int:
    """What the request body carries, near enough: base64 payloads plus the text."""
    docs = sum(
        image_fit.base64_len(len(d.data)) if d.media_type == "application/pdf" else len(d.data)
        for d in req.documents
    )
    pics = sum(image_fit.base64_len(len(i)) for i in images)
    text = sum(len(s.encode()) for s in (req.system, req.prompt, req.cache_prefix or ""))
    return docs + pics + text


#: Preflight with the count endpoint when the estimate is within 10% of the budget.
PREFLIGHT_SHARE = 0.9


class ClaudeProvider:
    """One attempt on a ``claude-`` model."""

    def __init__(self, adapter: AnthropicAdapter, settings: Settings) -> None:
        self._adapter = adapter
        self._settings = settings

    def _fit(self, req: LLMRequest, *, inline: bool) -> FittedImages:
        g = self._settings.gemini
        if inline and req.uploads is not None:
            # The job's handle fits the inline fallback once, not once per call.
            inline_fitted: FittedImages = req.uploads.inline_fit()
            return inline_fitted
        return image_fit.fit(
            [image.data for image in req.images],
            byte_limit=image_fit.DEFAULT_BYTE_LIMIT if inline else None,
            token_budget=g.claude_image_token_budget,
            floor_px=g.claude_image_floor_px,
            enhance=g.claude_image_enhance is True,
        )

    def _pages(
        self, req: LLMRequest, log: Any
    ) -> tuple[FittedImages | None, tuple[bytes, ...], tuple[str, ...]]:
        """The fit, and the inline images or the Files API ids to send.

        Uploads first (no inline byte limit); an upload failure falls back to inline
        base64, where the byte limit at the floor is the one refusal.
        """
        if not req.images:
            return None, (), ()
        if req.uploads is not None:
            try:
                fitted, file_ids = req.uploads.ensure()
                return fitted, (), file_ids
            except ExternalServiceError as exc:
                log.warning("claude_files_api_fallback", error=str(exc)[:200], tag=req.task_tag)
        fitted = self._fit(req, inline=True)
        if fitted.over_byte_limit:
            raise ProviderError(
                f"{len(req.images)} pages are {fitted.base64_bytes} bytes base64-encoded at "
                f"the {fitted.long_edge} px floor; one Claude request takes at most "
                f"{image_fit.DEFAULT_BYTE_LIMIT} bytes of inline images"
            )
        return fitted, fitted.images, ()

    def count_tokens(
        self,
        req: LLMRequest,
        *,
        images: tuple[bytes, ...] | None = None,
        file_ids: tuple[str, ...] = (),
        documents: Sequence[DocumentBlockParam] = (),
    ) -> int | None:
        """The count endpoint's figure for ``req``, or None if it fails.

        ``images`` and ``file_ids`` are the pages already prepared for sending; left
        out, the request's own images are fitted.
        """
        if images is None:
            images = self._fit(req, inline=True).images if req.images else ()
        try:
            return self._adapter.count_tokens(
                model=req.model,
                system_prompt=req.system,
                user_prompt=req.prompt,
                cache_prefix=req.cache_prefix,
                images=images,
                image_file_ids=file_ids,
                documents=documents,
            )
        except ExternalServiceError:
            return None

    def complete(self, req: LLMRequest, *, log: Any) -> ProviderReply:
        """Send ``req``; 429/529/5xx/connection raise ``TransientCallError``."""
        if req.response_schema is None:
            raise ProviderError("a Claude call needs a response schema")
        if any(d.citations for d in req.documents):
            raise ProviderError(
                "citations cannot be combined with a response schema (the API returns 400)"
            )
        documents = document_blocks(req.documents)
        fitted, images, file_ids = self._pages(req, log)
        size = _request_bytes(req, images)
        if size > MAX_REQUEST_BYTES:
            raise ProviderError(
                f"the request is {size} bytes; one Claude request takes at most {MAX_REQUEST_BYTES}"
            )
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
                counted = self.count_tokens(
                    req, images=images, file_ids=file_ids, documents=documents
                )
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
                documents=documents,
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
