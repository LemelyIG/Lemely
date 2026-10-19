"""One model request, whatever the provider (spec 2026-10-19 §1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import BaseModel

from lemely.io.providers import is_anthropic_model

Effort = Literal["low", "medium", "high", "xhigh", "max"]
CacheSpot = Literal["system", "documents", "images", "prefix"]
#: The API's limit on cache breakpoints in one request.
MAX_CACHE_BREAKPOINTS = 4


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


def provider_fingerprint(model: str, *, max_output_tokens: int) -> str:
    """The provider part of a reply's cache key: the single source for it.

    Empty for every Gemini model, so no Gemini key moves. A ``claude-`` model adds
    the provider name and the reply cap it is sent with.
    """
    if not is_anthropic_model(model):
        return ""
    return f"|provider=anthropic|max_tokens={max_output_tokens}"


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

    def fingerprint(self) -> str:
        """The provider part of this request's cache key (:func:`provider_fingerprint`)."""
        return provider_fingerprint(self.model, max_output_tokens=self.max_output_tokens)
