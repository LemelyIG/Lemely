"""What a provider returns, and the protocol every provider meets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from lemely.io.llm.request import LLMRequest


@dataclass(frozen=True)
class Usage:
    """Token counts for one Claude call, in the units ``CallRecord`` uses.

    ``input_tokens`` is the total input: uncached tokens, cache reads and cache
    writes. ``cached_tokens`` is the reads; the two write counts are the 5-minute
    and 1-hour writes (``usage.cache_creation``). ``output_tokens`` includes
    ``thinking_tokens``. ``container_seconds`` is billed code-execution time.
    """

    input_tokens: int
    cached_tokens: int
    output_tokens: int
    thinking_tokens: int
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    container_seconds: float = 0.0


@dataclass(frozen=True)
class ProviderReply:
    """One attempt's reply.

    ``usage_response`` is what ``GeminiClient._record_spend`` reads (an object with
    ``usage_metadata``). ``stop_reason`` is normalised: ``"max_tokens"`` for a reply
    cut off at its cap, ``"refusal"`` for a refusal, else the provider's own value or
    None. ``stop_detail`` is the provider's raw value as ``str()``.
    """

    text: str
    usage_response: Any
    stop_reason: str | None
    stop_detail: str
    latency_ms: int
    usage: Usage | None = None


class Provider(Protocol):
    """Turns one request into one reply. Retry, cache and spend stay in the client."""

    def complete(self, req: LLMRequest, *, log: Any) -> ProviderReply:
        """Send ``req`` once."""
        ...

    def count_tokens(self, req: LLMRequest) -> int | None:
        """The input tokens ``req`` would bill, or None when the provider cannot say."""
        ...
