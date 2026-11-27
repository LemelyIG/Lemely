"""Per-job LLM cost accumulator (billing spec §5.7 step 4).

``UsageMeter`` opens :func:`cost_scope` around a metered job. ``GeminiClient._record_spend``
(the one accounting path both providers reply through) calls :func:`record_llm_cost` with
each call's USD price. The scope is a contextvar holding a mutable, locked accumulator:
threads started under ``contextvars.copy_context().run`` share it (every pool under
``lemely/io`` does, pinned by ``tests/architecture/test_llm_threads_copy_context.py``); a
bare ``threading.Thread`` does not, which is why the web layer opens the scope inside the
worker thread, never in the request.

An inner scope shadows an outer one. Nothing here raises for a missing scope.
"""

from __future__ import annotations

import contextlib
import contextvars
import math
import threading
from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_MICRO = Decimal("0.000001")


class CostAccumulator:
    """A thread-safe running total of USD spent on model calls."""

    __slots__ = ("_calls", "_lock", "_total")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = Decimal(0)
        self._calls = 0

    def add(self, cost_usd: Decimal) -> None:
        """Add one call's cost. Refuses a negative or non-finite amount."""
        if not cost_usd.is_finite() or cost_usd < 0:
            raise ValueError(f"LLM cost must be finite and non-negative: {cost_usd!r}")
        with self._lock:
            self._total += cost_usd
            self._calls += 1

    @property
    def total_usd(self) -> Decimal:
        """The USD spent so far."""
        with self._lock:
            return self._total

    @property
    def calls(self) -> int:
        """How many priced calls were recorded."""
        with self._lock:
            return self._calls


_current: contextvars.ContextVar[CostAccumulator | None] = contextvars.ContextVar(
    "lemely_llm_cost", default=None
)


@contextlib.contextmanager
def cost_scope() -> Iterator[CostAccumulator]:
    """Collect every :func:`record_llm_cost` made in this context until exit."""
    accumulator = CostAccumulator()
    token = _current.set(accumulator)
    try:
        yield accumulator
    finally:
        _current.reset(token)


def record_llm_cost(cost_usd: Decimal) -> None:
    """Add ``cost_usd`` to the innermost open scope; a no-op outside any scope."""
    accumulator = _current.get()
    if accumulator is not None:
        accumulator.add(cost_usd)


def usd_decimal(value: float) -> Decimal:
    """``value`` USD as a Decimal rounded up to whole micro-dollars (``NUMERIC(12, 6)``).

    Rounded up so the total charged is never below the total spent.
    """
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"not a USD cost: {value!r}")
    return Decimal(repr(value)).quantize(_MICRO, rounding=ROUND_CEILING)
