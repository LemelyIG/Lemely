"""Claude models through the Anthropic Messages API (cost-ladder lever A1).

One request in, one reply out. :class:`lemely.io.gemini.GeminiClient` owns
everything around the request (response cache, cost ceiling, retry policy,
spend accounting) and dispatches here for any ``claude-`` model, so a task
tag moves to Claude by settings alone.

Data protection (user decision, 2026-10): student work goes only through the
synchronous Messages API. The Message Batches API is never used, whatever it
would save.

Scope: text in, structured JSON out. Phase A uses Anthropic for correction
only, so images and files are rejected before a request is built
(``GeminiClient.generate_structured``).

Mark bounds. Structured outputs cannot express numeric ``minimum`` /
``maximum``: :func:`anthropic.transform_schema` drops them from the schema
sent, so every reply is validated against the pydantic model in code, which
restores ``awarded_marks >= 0`` and ``0 <= confidence <= 1``. The upper bound
belongs to the question, not the schema. :meth:`AnthropicAdapter.generate`
enforces it when the caller passes ``max_awarded_marks``. The
``GeminiClient`` path does not know the question; there the bound stays
where it is for every provider, the clamp in
``lemely.io.correction_ai`` and ``CorrectedQuestion.validate_awarded_marks``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from lemely.io.providers import ProviderError, ProviderTransientError
from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from anthropic.types import Message, MessageParam, OutputConfigParam, TextBlockParam

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

        ``max_tokens`` truncated the JSON, so it is transient, the same rule as
        Gemini's ``MAX_TOKENS``. A ``refusal`` is permanent: the same request
        is refused again.
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
    ) -> AnthropicReply:
        """Send one request; return the unvalidated reply.

        ``thinking`` is a Lemely thinking level (see :func:`effort_for`);
        ``None`` sends no effort, leaving the model's default. The system
        prompt, and ``cache_prefix`` when given (sent as the first user block,
        ahead of ``user_prompt``), carry prompt-caching breakpoints.

        Raises:
            ProviderTransientError: 429, 529, any 5xx, or a connection failure.
            ProviderError: any other API error.
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
        if cache_prefix:
            message = {
                "role": "user",
                "content": [
                    {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": user_prompt},
                ],
            }
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
    ) -> tuple[_T, Usage]:
        """Send one request and return the validated reply with its usage.

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
