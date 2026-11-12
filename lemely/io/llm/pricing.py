"""Price rows with tiers and cache writes; Claude's rows (spec 2026-10-19 §3).

USD per 1k tokens, the convention ``lemely.io.gemini``'s tables use. Every Claude
rate was read from ``PRICING_URL`` on the date in ``CLAUDE_PRICE_SOURCES``; the
research numbers from brainstorming are not trusted on their own. ``inference_geo``
is never sent, so the 1.1x US-only multiplier never applies.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
#: Code execution: per container-hour, at least 5 minutes per execution. The
#: monthly free hours are ignored, so the ledger reads high, never low.
CODE_EXECUTION_USD_PER_CONTAINER_HOUR = 0.05
CODE_EXECUTION_MIN_BILLED_SECONDS = 300


class PriceRow(NamedTuple):
    """USD per 1k tokens. ``tier2`` applies above ``tier_threshold_tokens`` of total input.

    A row with no write rates bills cache writes at its input rate.
    """

    input: float
    cached_input: float
    output: float
    cache_write_5m: float | None = None
    cache_write_1h: float | None = None
    tier_threshold_tokens: int | None = None
    tier2: PriceRow | None = None


CLAUDE_PRICING: dict[str, PriceRow] = {
    "claude-haiku-5-5": PriceRow(
        0.000100,
        0.000010,
        0.000500,
        0.000125,
        0.000200,
        100_000,
        PriceRow(0.000500, 0.000050, 0.002500, 0.000625, 0.001000),
    ),
    "claude-sonnet-5-5": PriceRow(0.002000, 0.000100, 0.010000, 0.002500, 0.004000),
    "claude-opus-5-5": PriceRow(0.004000, 0.000200, 0.020000, 0.005000, 0.008000),
    "claude-fable-5-1": PriceRow(0.010000, 0.000250, 0.050000, 0.012500, 0.020000),
}
#: model -> (where the rates were read, the day they were read).
CLAUDE_PRICE_SOURCES: dict[str, tuple[str, date]] = {
    model: (PRICING_URL, date(2026, 10, 19)) for model in CLAUDE_PRICING
}


def claude_row(model: str) -> PriceRow | None:
    """The row whose key is the longest one contained in ``model``, or None."""
    for key in sorted(CLAUDE_PRICING, key=len, reverse=True):
        if key in model:
            return CLAUDE_PRICING[key]
    return None


def row_cost(
    row: PriceRow,
    *,
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    container_seconds: float = 0.0,
) -> float:
    """USD for one call. ``input_tokens`` is the total: uncached + reads + writes.

    The tier is chosen on that total. With no writes, no container time and no tier,
    the sum is formed in the same order as before, so Gemini costs are bit-identical.
    """
    total = max(input_tokens, 0)
    if (
        row.tier2 is not None
        and row.tier_threshold_tokens is not None
        and total > row.tier_threshold_tokens
    ):
        row = row.tier2
    cached = min(max(cached_tokens, 0), total)
    write_5m = max(cache_write_5m_tokens, 0)
    write_1h = max(cache_write_1h_tokens, 0)
    uncached = max(total - cached - write_5m - write_1h, 0)
    write_5m_rate = row.cache_write_5m if row.cache_write_5m is not None else row.input
    write_1h_rate = row.cache_write_1h if row.cache_write_1h is not None else row.input
    return (
        uncached / 1000 * row.input
        + cached / 1000 * row.cached_input
        + write_5m / 1000 * write_5m_rate
        + write_1h / 1000 * write_1h_rate
        + output_tokens / 1000 * row.output
        + container_seconds / 3600 * CODE_EXECUTION_USD_PER_CONTAINER_HOUR
    )
