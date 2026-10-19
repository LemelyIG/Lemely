"""Claude models through the Anthropic Messages API (cost-ladder lever A1).

One request in, one reply out. :class:`lemely.io.gemini.GeminiClient` owns
everything around the request (response cache, cost ceiling, retry policy,
spend accounting) and dispatches here for any ``claude-`` model, so a task
tag moves to Claude by settings alone.

Data protection (user decision, 2026-10): student work goes only through the
synchronous Messages API. The Message Batches API is never used, whatever it
would save.

Scope: text and page images in, structured JSON out. Images arrive as
encoded PNG or JPEG bytes (``GeminiClient.generate_structured``'s
``image_parts``) and are sent inline as base64 ``image`` blocks, ahead of the
text, in the order given. Files (``file_paths``) are still rejected before a
request is built, and Gemini's own image knobs do not apply: ``image_uploads``
(Files API handles) and ``media_resolution`` are ignored for a ``claude-``
model, which always gets the bytes themselves.

Image limits (https://platform.claude.com/docs/en/build-with-claude/vision,
read 2026-10-19). A page whose long edge is over :data:`MAX_LONG_EDGE` (the
long edge Claude 4.7-and-later models read natively; the API would scale it
down to that anyway, so nothing the model sees is lost), or over
:data:`MANY_IMAGES_LONG_EDGE` when the request holds more than
:data:`MANY_IMAGES_THRESHOLD` images (the API refuses bigger ones then), is
scaled down here, keeping its aspect ratio and its format. Everything else is
sent byte for byte. A request that would still break a hard limit (more than
:data:`MAX_IMAGES_PER_REQUEST` images, one image over
:data:`MAX_IMAGE_BASE64_BYTES` encoded, or all of them over
:data:`MAX_IMAGES_BASE64_TOTAL`) raises :class:`ProviderError` before it is
sent: pages are never recompressed lossily to squeeze under a limit, since a
handwriting read on degraded pages would fail silently instead of loudly.

Mark bounds. Structured outputs cannot express numeric ``minimum`` /
``maximum``: :func:`anthropic.transform_schema` drops them from the schema
sent, so every reply is validated against the pydantic model in code (by
``GeminiClient.generate_structured`` on the production path), which restores
``awarded_marks >= 0`` and ``0 <= confidence <= 1``. The upper bound belongs to
the question, not the schema. :meth:`AnthropicAdapter.complete`, the method
``GeminiClient`` calls, returns the reply unvalidated and does not check it;
the bound is enforced where it is for every provider, the clamp in
``lemely.io.correction_ai`` and ``CorrectedQuestion.validate_awarded_marks``.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeVar

import anthropic
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ValidationError

from lemely.io.providers import ProviderError, ProviderTransientError
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from anthropic.types import (
        Base64ImageSourceParam,
        ContentBlockParam,
        ImageBlockParam,
        Message,
        MessageParam,
        OutputConfigParam,
        TextBlockParam,
    )

_T = TypeVar("_T", bound=BaseModel)

Effort = Literal["low", "medium", "high"]

#: Reply budget per call. A marking reply is a few hundred tokens plus
#: thinking; 16k keeps a non-streaming request well inside the SDK's
#: ten-minute non-streaming limit (Gemini's 65536 would not be).
MAX_OUTPUT_TOKENS = 16_000

#: Lemely thinking levels (``GeminiSettings.thinking_level_for``) to Anthropic
#: ``output_config.effort``. Anthropic has no "minimal"; it maps to "low".
_EFFORT_FOR_LEVEL: dict[str, Effort] = {
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
}

#: A 5-minute cache write bills at 1.25x the base input rate.
_CACHE_WRITE_PREMIUM_NUM, _CACHE_WRITE_PREMIUM_DEN = 5, 4

#: 429 rate limit, 529 overloaded, and every 5xx are retried by the client.
_TRANSIENT_STATUS = frozenset({429, 529})

#: The longest edge, in pixels, a Claude 4.7-and-later model reads natively.
MAX_LONG_EDGE = 2576
#: Above this many images in one request the API holds every image to
#: :data:`MANY_IMAGES_LONG_EDGE` on both dimensions.
MANY_IMAGES_THRESHOLD = 20
MANY_IMAGES_LONG_EDGE = 2000
#: The API's image cap for a 200k-context model (600 for the others); the lower
#: one, since a binding read is a few dozen pages at most.
MAX_IMAGES_PER_REQUEST = 100
#: One image, base64-encoded (the API's limit is 10 MB).
MAX_IMAGE_BASE64_BYTES = 10_000_000
#: Every image of one request, base64-encoded: the API's 32 MB request limit
#: less room for the prompt and the response schema.
MAX_IMAGES_BASE64_TOTAL = 30_000_000

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_MediaType = Literal["image/png", "image/jpeg"]


def effort_for(level: str) -> Effort:
    """The Anthropic effort for a Lemely thinking level; unknown levels raise ``ValueError``."""
    try:
        return _EFFORT_FOR_LEVEL[level]
    except KeyError:
        raise ValueError(
            f"No Anthropic effort for thinking level {level!r}; "
            f"expected one of {sorted(_EFFORT_FOR_LEVEL)}"
        ) from None


@dataclass(frozen=True)
class Usage:
    """Token counts for one call, in the units ``CallRecord`` uses.

    ``input_tokens`` is the billing-equivalent input count: uncached tokens,
    cache reads, and cache writes weighted by the 1.25x premium Anthropic
    charges for a 5-minute cache write (Anthropic reports the three
    separately). Priced as uncached input minus ``cached_tokens`` at the input
    rate, this reproduces the exact bill. ``cached_tokens`` is the cache reads,
    billed at the cached rate. ``output_tokens`` includes ``thinking_tokens``,
    as Anthropic's own total does.
    """

    input_tokens: int
    cached_tokens: int
    output_tokens: int
    thinking_tokens: int


@dataclass(frozen=True)
class AnthropicReply:
    """The raw reply: the JSON text, its usage and why generation stopped."""

    text: str
    usage: Usage
    stop_reason: str | None

    def raise_for_stop_reason(self, model: str) -> None:
        """Raise when the reply cannot be used as it stands.

        ``max_tokens`` truncated the JSON: transient here (for
        :meth:`AnthropicAdapter.generate`). ``GeminiClient`` checks
        ``max_tokens`` itself before calling this and treats it like a Gemini
        reply cut off at a per-tag cap (one fresh retry, then fail), so on the
        production path only the refusal rule applies. A ``refusal`` is
        permanent: the same request is refused again.
        """
        if self.stop_reason == "max_tokens":
            raise ProviderTransientError(f"Anthropic hit max_tokens ({model})")
        if self.stop_reason == "refusal":
            raise ProviderError(f"Anthropic refused the request ({model})")


def _usage_of(message: Message) -> Usage:
    u = message.usage
    cache_read = int(u.cache_read_input_tokens or 0)
    cache_write = int(u.cache_creation_input_tokens or 0)
    details = u.output_tokens_details
    return Usage(
        input_tokens=int(u.input_tokens)
        + cache_read
        + -(-cache_write * _CACHE_WRITE_PREMIUM_NUM // _CACHE_WRITE_PREMIUM_DEN),
        cached_tokens=cache_read,
        output_tokens=int(u.output_tokens),
        thinking_tokens=int(details.thinking_tokens) if details is not None else 0,
    )


def _media_type(data: bytes, page: int) -> _MediaType:
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    raise ProviderError(f"page {page} is neither PNG nor JPEG; Claude is sent only those")


def _fit(data: bytes, media_type: _MediaType, long_edge: int, page: int) -> bytes:
    """``data`` as it is, or scaled down so its long edge is ``long_edge``, same format."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if max(width, height) <= long_edge:
                return data
            scale = long_edge / max(width, height)
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            fmt = "PNG" if media_type == "image/png" else "JPEG"
            img.load()
            work: Image.Image = img
            if work.mode not in ("L", "RGB") and not (fmt == "PNG" and work.mode in ("LA", "RGBA")):
                work = work.convert("RGBA" if fmt == "PNG" and "A" in work.getbands() else "RGB")
            resized = work.resize(size, Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProviderError(f"page {page} could not be read as an image: {exc}") from exc
    out = io.BytesIO()
    if fmt == "JPEG":
        resized.save(out, fmt, quality=95)
    else:
        resized.save(out, fmt)
    return out.getvalue()


def image_blocks(images: Sequence[bytes]) -> list[ImageBlockParam]:
    """Base64 ``image`` blocks for ``images``, in order, held to the API's limits.

    See the module docstring for what is scaled down and what is refused.

    Raises:
        ProviderError: a page is not a readable PNG or JPEG, or the request would
            break a limit that scaling down to the native size does not meet.
    """
    if len(images) > MAX_IMAGES_PER_REQUEST:
        raise ProviderError(
            f"{len(images)} images in one Claude request; the limit is {MAX_IMAGES_PER_REQUEST}"
        )
    long_edge = MANY_IMAGES_LONG_EDGE if len(images) > MANY_IMAGES_THRESHOLD else MAX_LONG_EDGE
    blocks: list[ImageBlockParam] = []
    total = 0
    for page, data in enumerate(images, start=1):
        media_type = _media_type(data, page)
        encoded = base64.standard_b64encode(_fit(data, media_type, long_edge, page)).decode("ascii")
        if len(encoded) > MAX_IMAGE_BASE64_BYTES:
            raise ProviderError(
                f"page {page} is {len(encoded)} bytes base64-encoded; Claude takes at most "
                f"{MAX_IMAGE_BASE64_BYTES} per image"
            )
        total += len(encoded)
        source: Base64ImageSourceParam = {
            "type": "base64",
            "media_type": media_type,
            "data": encoded,
        }
        blocks.append({"type": "image", "source": source})
    if total > MAX_IMAGES_BASE64_TOTAL:
        raise ProviderError(
            f"{len(images)} pages are {total} bytes base64-encoded; one Claude request takes "
            f"at most {MAX_IMAGES_BASE64_TOTAL} of images"
        )
    return blocks


def _is_transient(exc: anthropic.APIError) -> bool:
    if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in _TRANSIENT_STATUS or exc.status_code >= 500
    return False


class AnthropicAdapter:
    """Structured-output calls to Claude through the synchronous Messages API."""

    def __init__(self, client: anthropic.Anthropic) -> None:
        self._client = client

    @classmethod
    def from_api_key(cls, api_key: str) -> AnthropicAdapter:
        """An adapter on a real SDK client.

        ``max_retries=0``: ``GeminiClient``'s retry policy is the only one, so
        a retried call is counted and logged once, not silently multiplied.
        """
        return cls(anthropic.Anthropic(api_key=api_key, max_retries=0))

    def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel],
        thinking: str | None,
        cache_prefix: str | None,
        images: Sequence[bytes] = (),
    ) -> AnthropicReply:
        """Send one request; return the unvalidated reply.

        ``thinking`` is a Lemely thinking level (see :func:`effort_for`);
        ``None`` sends no effort, leaving the model's default. The system
        prompt, and ``cache_prefix`` when given (sent as a user text block
        ahead of ``user_prompt``), carry prompt-caching breakpoints.
        ``images`` (PNG or JPEG bytes) go first in the user message, as
        :func:`image_blocks` builds them, so the model sees the pages before
        the question about them.

        Raises:
            ProviderTransientError: 429, 529, any 5xx, or a connection failure.
            ProviderError: any other API error, or ``images`` the API would
                refuse (:func:`image_blocks`).
        """
        output_config: OutputConfigParam = {
            "format": {
                "type": "json_schema",
                "schema": anthropic.transform_schema(response_schema),
            }
        }
        if thinking is not None:
            output_config["effort"] = effort_for(thinking)
        system: list[TextBlockParam] = (
            [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
            if system_prompt
            else []
        )
        message: MessageParam
        if cache_prefix or images:
            content: list[ContentBlockParam] = [*image_blocks(images)]
            if cache_prefix:
                content.append(
                    {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}}
                )
            content.append({"type": "text", "text": user_prompt})
            message = {"role": "user", "content": content}
        else:
            message = {"role": "user", "content": user_prompt}
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=[message],
                thinking={"type": "adaptive"},
                output_config=output_config,
            )
        except anthropic.APIError as exc:
            if _is_transient(exc):
                raise ProviderTransientError(str(exc)) from exc
            raise ProviderError(str(exc)) from exc
        text = "".join(block.text for block in response.content if block.type == "text")
        return AnthropicReply(
            text=text, usage=_usage_of(response), stop_reason=response.stop_reason
        )

    def generate(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[_T],
        thinking: str | None,
        cache_prefix: str | None,
        max_awarded_marks: int | None = None,
        images: Sequence[bytes] = (),
    ) -> tuple[_T, Usage]:
        """Send one request and return the validated reply with its usage.

        A test helper: production calls go through ``GeminiClient``, which
        calls :meth:`complete` and owns validation, retries and spend. Only
        this helper checks ``max_awarded_marks``.

        Raises:
            ProviderTransientError: as :meth:`complete`, or the reply was cut
                off at ``max_tokens``.
            ProviderError: as :meth:`complete`, or the model refused.
            ParseError: the reply does not validate against ``response_schema``,
                or its ``awarded_marks`` exceeds ``max_awarded_marks``.
        """
        reply = self.complete(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            thinking=thinking,
            cache_prefix=cache_prefix,
            images=images,
        )
        reply.raise_for_stop_reason(model)
        try:
            parsed = response_schema.model_validate_json(reply.text)
        except ValidationError as exc:
            raise ParseError(
                f"Anthropic reply did not validate against {response_schema.__name__}: {exc}"
            ) from exc
        awarded = getattr(parsed, "awarded_marks", None)
        if (
            max_awarded_marks is not None
            and isinstance(awarded, int)
            and awarded > max_awarded_marks
        ):
            raise ParseError(
                f"Anthropic reply awarded {awarded} marks; the question allows {max_awarded_marks}"
            )
        return parsed, reply.usage
