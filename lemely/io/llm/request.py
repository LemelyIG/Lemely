"""One model request, whatever the provider (spec 2026-10-19 §1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import BaseModel

from lemely.io.providers import is_anthropic_model

Effort = Literal["none", "low", "medium", "high", "xhigh", "max"]
CacheSpot = Literal["system", "documents", "images", "prefix"]
#: Claude's server-side code-execution tool version (docs read 2026-10-20: latest).
CODE_EXECUTION_TOOL = "code_execution_20260521"
#: The API's limit on cache breakpoints in one request.
MAX_CACHE_BREAKPOINTS = 4
#: Below this many tokens a cache breakpoint is not placed (5.5 models' minimum).
CACHE_MIN_TOKENS = 512
#: Text-length estimate of tokens.
CHARS_PER_TOKEN = 4
#: Version of the ``Page index {i}:`` text blocks put before each image of a Claude
#: request that carries several (``anthropic_adapter.labelled_pictures``). It joins the
#: Claude cache key for those requests. Why: with bare image blocks Haiku numbered a
#: 19-page script 1..19 in 3 of 22 reads (.superpowers/sdd/binding-investigation.md).
PAGE_LABEL_VERSION = "v1"


@dataclass(frozen=True)
class ImageInput:
    """One page image as encoded bytes."""

    data: bytes
    media_type: Literal["image/png", "image/jpeg"] = "image/png"


@dataclass(frozen=True)
class DocumentInput:
    """One document. ``source_path`` is kept for Gemini's Files API, which uploads a path."""

    data: bytes
    media_type: Literal["application/pdf", "text/plain"] = "application/pdf"
    cache: bool = False
    citations: bool = False
    title: str | None = None
    source_path: Path | None = None

    @classmethod
    def from_path(cls, path: Path, **kwargs: Any) -> DocumentInput:
        """The document at ``path``: its bytes, and the path itself for Gemini."""
        return cls(data=path.read_bytes(), source_path=path, **kwargs)


@dataclass(frozen=True)
class CodeExecution:
    """Ask the provider's own server-side code-execution tool to run code."""


@dataclass(frozen=True)
class CachePlan:
    """Where a Claude request places its prompt-cache breakpoints (spec §4 B1)."""

    breakpoints: tuple[CacheSpot, ...] = ()
    ttl: Literal["5m"] = "5m"

    def __post_init__(self) -> None:
        """Refuse more than the API's four breakpoints, or one spot named twice."""
        if len(self.breakpoints) > MAX_CACHE_BREAKPOINTS:
            raise ValueError(
                f"at most {MAX_CACHE_BREAKPOINTS} cache breakpoints, got {len(self.breakpoints)}"
            )
        if len(set(self.breakpoints)) != len(self.breakpoints):
            raise ValueError(f"cache breakpoints named twice: {self.breakpoints}")


#: The breakpoints every claude- call has placed since lever A1.
LEGACY_CLAUDE_CACHE_PLAN = CachePlan(breakpoints=("system", "prefix"))


def provider_fingerprint(
    model: str,
    *,
    max_output_tokens: int,
    image_token_budget: int,
    image_floor_px: int,
    image_enhance: bool,
    response_schema: type[BaseModel] | None = None,
    image_count: int = 0,
) -> str:
    """The provider part of a reply's cache key: the single source for it.

    Empty for every Gemini model, so no Gemini key moves. A ``claude-`` model adds
    the provider name, the reply cap it is sent with, the page-image fit version and
    the token budget, pixel floor and enhancement that fit uses (each changes the pixels
    sent; ``image_enhance`` selects the fit version). When ``response_schema`` takes the
    prompt-JSON route, ``|pj=<PROMPT_JSON_VERSION>`` is appended, since the instruction
    wording is part of what is sent. A request with more than one image is sent with a
    page-index label before each (``|pg_lbl=<PAGE_LABEL_VERSION>``).
    """
    if not is_anthropic_model(model):
        return ""
    # Read at call time, and imported here, so importing this module stays free of Pillow.
    from lemely.io.llm import image_fit

    fingerprint = (
        f"|provider=anthropic|max_tokens={max_output_tokens}|img_fit={image_fit.img_fit_version(enhance=image_enhance)}"
        f"|img_budget={image_token_budget}|img_floor={image_floor_px}"
    )
    if response_schema is not None:
        from lemely.io.providers.claude_schema import PROMPT_JSON_VERSION, prompt_json_for

        if prompt_json_for(response_schema):
            fingerprint += f"|pj={PROMPT_JSON_VERSION}"
    if image_count > 1:
        fingerprint += f"|pg_lbl={PAGE_LABEL_VERSION}"
    return fingerprint


@dataclass(frozen=True)
class LLMRequest:
    """Everything one attempt sends; built by ``GeminiClient`` and read by a provider.

    ``effort`` is the provider's own effort value (Claude) or None. ``uploads`` is a
    provider's uploads handle (Gemini ``ImageUploads``, Claude ``ClaudeImageUploads``).
    ``shared_prefix`` is a Gemini-only ``SharedPrefix`` for its explicit cache; on
    Claude the prefix arrives split into ``system`` and ``cache_prefix``.
    """

    model: str
    task_tag: str | None
    system: str
    prompt: str
    response_schema: type[BaseModel] | None
    images: tuple[ImageInput, ...] = ()
    documents: tuple[DocumentInput, ...] = ()
    tool: CodeExecution | None = None
    cache_plan: CachePlan = field(default_factory=CachePlan)
    effort: str | None = None
    max_output_tokens: int = 65536
    cache_prefix: str | None = None
    media_resolution: str | None = None
    uploads: Any = None
    shared_prefix: Any = None

    def fingerprint(
        self, *, image_token_budget: int, image_floor_px: int, image_enhance: bool
    ) -> str:
        """The provider part of this request's cache key (:func:`provider_fingerprint`)."""
        return provider_fingerprint(
            self.model,
            max_output_tokens=self.max_output_tokens,
            image_token_budget=image_token_budget,
            image_floor_px=image_floor_px,
            image_enhance=image_enhance,
            response_schema=self.response_schema,
            image_count=len(self.images),
        )
