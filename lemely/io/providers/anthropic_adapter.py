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
``image_parts``). With ``gemini.claude_files_api`` on (the default) the provider
uploads them once per job to Anthropic's Files API and sends ``image`` blocks that
reference the file ids; if the upload fails, or the flag is off, they go inline as
base64 ``image`` blocks. Either way the user message is ordered documents, images
(in the order given), the cached prefix text, then the prompt. Files (``file_paths``)
are still rejected before a request is built, and Gemini's own image knobs do not
apply: Gemini's ``image_uploads`` handles are replaced by the Claude uploads described
above, and ``media_resolution`` is ignored for a ``claude-`` model.

Images arrive already fitted by ``lemely.io.llm.image_fit`` (greyscale, long
edge, token and byte budgets). This module only checks what the API would refuse
outright: the media type, more than :data:`MAX_IMAGES_PER_REQUEST` images, or one
image over :data:`MAX_IMAGE_BASE64_BYTES` encoded.

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
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

import anthropic
from PIL import Image
from pydantic import BaseModel, ValidationError

from lemely.io.llm.image_fit import estimate_tokens
from lemely.io.llm.provider import Usage
from lemely.io.llm.request import (
    CACHE_MIN_TOKENS,
    CHARS_PER_TOKEN,
    LEGACY_CLAUDE_CACHE_PLAN,
    MAX_CACHE_BREAKPOINTS,
    CachePlan,
)
from lemely.io.providers import ProviderError, ProviderTransientError
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from anthropic.types import (
        Base64ImageSourceParam,
        CacheControlEphemeralParam,
        ContentBlock,
        ContentBlockParam,
        DocumentBlockParam,
        FileImageSourceParam,
        ImageBlockParam,
        Message,
        MessageParam,
        OutputConfigParam,
        TextBlockParam,
    )

_T = TypeVar("_T", bound=BaseModel)

_RESULT_BLOCKS = frozenset({"bash_code_execution_tool_result", "code_execution_tool_result"})
_RESULT_CONTENT = frozenset({"bash_code_execution_result", "code_execution_result"})


def _usage_ran_code(message: Message) -> bool:
    """Whether the usage counter reports a code-execution request."""
    server_use = getattr(
        getattr(message.usage, "server_tool_use", None), "code_execution_requests", 0
    )
    return isinstance(server_use, int) and server_use > 0


def code_execution_output(message: Message) -> tuple[str, bool]:
    """What the code printed (last successful run), else the final text; and whether code ran."""
    return _output_of(message.content, _usage_ran_code(message))


def _output_of(blocks: Sequence[ContentBlock], ran: bool) -> tuple[str, bool]:
    """:func:`code_execution_output` over content blocks (several legs concatenated)."""
    stdout: str | None = None
    for block in blocks:
        if getattr(block, "type", None) == "server_tool_use":
            ran = True
        if getattr(block, "type", None) not in _RESULT_BLOCKS:
            continue
        ran = True
        content = getattr(block, "content", None)
        if getattr(content, "type", None) not in _RESULT_CONTENT:
            continue
        out = getattr(content, "stdout", "") or ""
        if getattr(content, "return_code", 1) == 0 and out.strip():
            stdout = out
    if stdout is not None:
        return stdout.strip(), ran
    if not ran:
        # Prose with no code run is not sandbox output (Gemini behaves the same).
        return "", False
    texts = [b.text for b in blocks if b.type == "text"]
    return (texts[-1].strip() if texts else ""), ran


#: Resends of a ``pause_turn`` reply before the call gives up with no answer.
MAX_PAUSE_CONTINUATIONS = 3

EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
Effort = Literal["low", "medium", "high", "xhigh", "max"]

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

#: 408 timeout, 409 conflict, 429 rate limit, 529 overloaded, and every 5xx are retried
#: by the client (the Anthropic SDK's own retry policy retries the same statuses).
_TRANSIENT_STATUS = frozenset({408, 409, 429, 529})

#: The API's image cap per request: 100 for a model with a 200k-token context window,
#: 600 for every other (platform.claude.com/docs/en/build-with-claude/vision, "Request
#: limits", read 2026-10-23). The lower one holds for all, and a binding read (chunked
#: or not) is a few dozen pages at most.
MAX_IMAGES_PER_REQUEST = 100
#: One image, base64-encoded (the API's limit is 10 MB).
MAX_IMAGE_BASE64_BYTES = 10_000_000

#: The SDK refuses a non-streaming request whose max_tokens implies more than ten
#: minutes (3600 * max_tokens / 128000 > 600); above this the reply is streamed.
NONSTREAMING_MAX_TOKENS = 21_333

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_MediaType = Literal["image/png", "image/jpeg"]


def _as_effort(value: str) -> Effort:
    """An effort passes as it is; a Lemely thinking level maps through effort_for."""
    return cast("Effort", value) if value in EFFORTS else effort_for(value)


def resolve_effort(
    efforts: Mapping[str, Effort] | object,
    thinking_levels: Mapping[str, str],
    tag: str,
    kind: str | None = None,
) -> Effort:
    """Claude effort for a task tag: ``tag:kind``, then ``tag``, then its thinking level.

    ``efforts`` is ``GeminiSettings.claude_effort_for``; anything that is not a dict
    (a stand-in settings object) counts as empty.
    """
    table: Mapping[str, Effort] = efforts if isinstance(efforts, dict) else {}
    return (
        (table.get(f"{tag}:{kind}") if kind else None)
        or table.get(tag)
        or effort_for(thinking_levels.get(tag, "low"))
    )


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
class AnthropicReply:
    """The raw reply: the JSON text, its usage and why generation stopped."""

    text: str
    usage: Usage
    stop_reason: str | None
    ran_code: bool = False

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


def _add_usage(total: Usage, more: Usage) -> Usage:
    """``total`` plus ``more``, field by field (the legs of a paused turn)."""
    return Usage(
        input_tokens=total.input_tokens + more.input_tokens,
        cached_tokens=total.cached_tokens + more.cached_tokens,
        output_tokens=total.output_tokens + more.output_tokens,
        thinking_tokens=total.thinking_tokens + more.thinking_tokens,
        cache_write_5m_tokens=total.cache_write_5m_tokens + more.cache_write_5m_tokens,
        cache_write_1h_tokens=total.cache_write_1h_tokens + more.cache_write_1h_tokens,
    )


def _usage_of(message: Message) -> Usage:
    u = message.usage
    cache_read = int(u.cache_read_input_tokens or 0)
    creation = getattr(u, "cache_creation", None)
    if creation is not None:
        write_5m = int(creation.ephemeral_5m_input_tokens or 0)
        write_1h = int(creation.ephemeral_1h_input_tokens or 0)
    else:
        write_5m, write_1h = int(u.cache_creation_input_tokens or 0), 0
    details = u.output_tokens_details
    return Usage(
        input_tokens=int(u.input_tokens) + cache_read + write_5m + write_1h,
        cached_tokens=cache_read,
        output_tokens=int(u.output_tokens),
        thinking_tokens=int(details.thinking_tokens) if details is not None else 0,
        cache_write_5m_tokens=write_5m,
        cache_write_1h_tokens=write_1h,
    )


def _media_type(data: bytes, page: int) -> _MediaType:
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    raise ProviderError(f"page {page} is neither PNG nor JPEG; Claude is sent only those")


def image_blocks(images: Sequence[bytes]) -> list[ImageBlockParam]:
    """Base64 ``image`` blocks for already-fitted ``images``, in order.

    Raises:
        ProviderError: a page is not PNG or JPEG, one is over the per-image size,
            or there are more images than the API takes.
    """
    if len(images) > MAX_IMAGES_PER_REQUEST:
        raise ProviderError(
            f"{len(images)} images in one Claude request; the limit is {MAX_IMAGES_PER_REQUEST}"
        )
    blocks: list[ImageBlockParam] = []
    for page, data in enumerate(images, start=1):
        media_type = _media_type(data, page)
        encoded = base64.standard_b64encode(data).decode("ascii")
        if len(encoded) > MAX_IMAGE_BASE64_BYTES:
            raise ProviderError(
                f"page {page} is {len(encoded)} bytes base64-encoded; Claude takes at most "
                f"{MAX_IMAGE_BASE64_BYTES} per image"
            )
        source: Base64ImageSourceParam = {
            "type": "base64",
            "media_type": media_type,
            "data": encoded,
        }
        blocks.append({"type": "image", "source": source})
    return blocks


def file_image_blocks(file_ids: Sequence[str]) -> list[ImageBlockParam]:
    """``image`` blocks that reference Files API uploads by id, in order."""
    if len(file_ids) > MAX_IMAGES_PER_REQUEST:
        raise ProviderError(
            f"{len(file_ids)} images in one Claude request; the limit is {MAX_IMAGES_PER_REQUEST}"
        )
    return [
        {"type": "image", "source": cast("FileImageSourceParam", {"type": "file", "file_id": fid})}
        for fid in file_ids
    ]


_EPHEMERAL: CacheControlEphemeralParam = {"type": "ephemeral"}


def _image_tokens(data: bytes) -> int:
    with Image.open(io.BytesIO(data)) as img:
        return estimate_tokens(*img.size)


def _request_parts(
    *,
    system_prompt: str,
    user_prompt: str,
    cache_prefix: str | None,
    documents: Sequence[DocumentBlockParam],
    images: Sequence[bytes],
    image_file_ids: Sequence[str],
    cache_plan: CachePlan | None,
) -> tuple[list[TextBlockParam], MessageParam]:
    """System blocks and the user message, with breakpoints where the plan and size allow.

    Order: system, documents, images, prefix, per-call text. A spot is marked only
    when the estimated tokens up to and including it reach CACHE_MIN_TOKENS.
    """
    spots = set((cache_plan or LEGACY_CLAUDE_CACHE_PLAN).breakpoints)
    running = len(system_prompt) // CHARS_PER_TOKEN
    system: list[TextBlockParam] = []
    if system_prompt:
        block: TextBlockParam = {"type": "text", "text": system_prompt}
        if "system" in spots and running >= CACHE_MIN_TOKENS:
            block["cache_control"] = _EPHEMERAL
        system.append(block)
    docs = [cast("DocumentBlockParam", dict(d)) for d in documents]
    for doc in docs:
        source = cast("dict[str, str]", doc["source"])
        running += (
            len(source["data"]) // CHARS_PER_TOKEN if source["type"] == "text" else CACHE_MIN_TOKENS
        )
    if docs and "documents" in spots and running >= CACHE_MIN_TOKENS:
        docs[-1]["cache_control"] = _EPHEMERAL
    pictures = [*image_blocks(images), *file_image_blocks(image_file_ids)]
    running += sum(_image_tokens(i) for i in images) + CACHE_MIN_TOKENS * len(image_file_ids)
    if pictures and "images" in spots and running >= CACHE_MIN_TOKENS:
        pictures[-1]["cache_control"] = _EPHEMERAL
    content: list[ContentBlockParam] = [*docs, *pictures]
    if cache_prefix:
        running += len(cache_prefix) // CHARS_PER_TOKEN
        prefix: TextBlockParam = {"type": "text", "text": cache_prefix}
        if "prefix" in spots and running >= CACHE_MIN_TOKENS:
            prefix["cache_control"] = _EPHEMERAL
        content.append(prefix)
    marked = sum(1 for b in [*system, *content] if "cache_control" in b)
    if marked > MAX_CACHE_BREAKPOINTS:
        raise ProviderError(
            f"{marked} cache breakpoints in one Claude request; "
            f"the limit is {MAX_CACHE_BREAKPOINTS}"
        )
    if not content:
        return system, {"role": "user", "content": user_prompt}
    content.append({"type": "text", "text": user_prompt})
    return system, {"role": "user", "content": content}


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

    @property
    def raw(self) -> anthropic.Anthropic:
        """The SDK client (the Files API uploads use it)."""
        return self._client

    def _send(self, **kwargs: Any) -> Message:  # type: ignore[explicit-any]  # noqa: ANN401
        """One request; streamed when ``max_tokens`` is past the SDK's non-streaming limit.

        Some models have a per-model non-streaming limit below 21,333 tokens, so a cap
        under the threshold can still be refused by the API.
        """
        try:
            if kwargs["max_tokens"] > NONSTREAMING_MAX_TOKENS:
                with self._client.messages.stream(**kwargs) as stream:
                    return cast("Message", stream.get_final_message())
            return cast("Message", self._client.messages.create(**kwargs))
        except anthropic.APIError as exc:
            if _is_transient(exc):
                raise ProviderTransientError(str(exc)) from exc
            raise ProviderError(str(exc)) from exc

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
        image_file_ids: Sequence[str] = (),
        documents: Sequence[DocumentBlockParam] = (),
        max_tokens: int = MAX_OUTPUT_TOKENS,
        cache_plan: CachePlan | None = None,
    ) -> AnthropicReply:
        """Send one request; return the unvalidated reply.

        ``documents`` are ``document`` blocks and go before everything else.
        ``images`` are already fitted (``lemely.io.llm.image_fit``) and go first, as
        base64 blocks; ``image_file_ids`` reference the same kind of pages uploaded
        through the Files API. ``max_tokens`` above :data:`NONSTREAMING_MAX_TOKENS`
        is streamed.

        Raises:
            ProviderTransientError: 429, 529, any 5xx, or a connection failure.
            ProviderError: any other API error, or images the API would refuse.
        """
        output_config: OutputConfigParam = {
            "format": {
                "type": "json_schema",
                "schema": anthropic.transform_schema(response_schema),
            }
        }
        if thinking is not None:
            output_config["effort"] = _as_effort(thinking)
        system, message = _request_parts(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cache_prefix=cache_prefix,
            documents=documents,
            images=images,
            image_file_ids=image_file_ids,
            cache_plan=cache_plan,
        )
        response = self._send(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[message],
            thinking={"type": "adaptive"},
            output_config=output_config,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return AnthropicReply(
            text=text, usage=_usage_of(response), stop_reason=response.stop_reason
        )

    def complete_code_execution(
        self, *, model: str, prompt: str, thinking: str | None, max_tokens: int = MAX_OUTPUT_TOKENS
    ) -> AnthropicReply:
        """Claude's code-execution tool; plain text, no response schema.

        Loops through ``pause_turn`` continuations (up to ``MAX_PAUSE_CONTINUATIONS``)
        in one container. The answer is the last successful stdout across all legs,
        else the final text if code ran; a cut-off, refused or still-paused reply is "".
        """
        from lemely.io.llm.request import CODE_EXECUTION_TOOL

        extra: dict[str, object] = {}
        if thinking is not None:
            extra["output_config"] = {"effort": _as_effort(thinking)}
        messages: list[MessageParam] = [{"role": "user", "content": prompt}]
        usage = Usage(0, 0, 0, 0)
        ran_code = False
        content: list[ContentBlock] = []
        container_id: str | None = None
        for _ in range(MAX_PAUSE_CONTINUATIONS + 1):
            if container_id is not None:
                extra["container"] = container_id
            response = self._send(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                tools=[{"type": CODE_EXECUTION_TOOL, "name": "code_execution"}],
                thinking={"type": "adaptive"},
                **extra,
            )
            usage = _add_usage(usage, _usage_of(response))
            content.extend(response.content)
            ran_code = ran_code or _usage_ran_code(response)
            text, ran_code = _output_of(content, ran_code)
            if response.stop_reason != "pause_turn":
                if response.stop_reason in ("max_tokens", "refusal"):
                    text = ""
                return AnthropicReply(
                    text=text, usage=usage, stop_reason=response.stop_reason, ran_code=ran_code
                )
            # Official docs: a paused turn is sent back as-is to continue; the
            # response's container id is passed back so it stays one container.
            messages = [*messages, {"role": "assistant", "content": response.content}]
            container = getattr(response, "container", None)
            container_id = getattr(container, "id", None) or container_id
        # Still paused after the cap: no usable answer (an empty text is never cached).
        return AnthropicReply(text="", usage=usage, stop_reason="pause_turn", ran_code=ran_code)

    def count_tokens(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        cache_prefix: str | None,
        images: Sequence[bytes] = (),
        image_file_ids: Sequence[str] = (),
        documents: Sequence[DocumentBlockParam] = (),
        cache_plan: CachePlan | None = None,
    ) -> int:
        """Input tokens the request would bill, from the free count endpoint.

        Raises:
            ProviderError: the endpoint failed (a preflight caller treats it as unknown).
        """
        system, message = _request_parts(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cache_prefix=cache_prefix,
            documents=documents,
            images=images,
            image_file_ids=image_file_ids,
            cache_plan=cache_plan,
        )
        try:
            counted = self._client.messages.count_tokens(
                model=model, system=system, messages=[message]
            )
        except anthropic.APIError as exc:
            raise ProviderError(str(exc)) from exc
        return int(counted.input_tokens)

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
