"""Per-model split of a usage job's LLM cost (Phase 07 task 3).

The sibling of :mod:`lemely.io.llm.cost_meter`: where that keeps one running total per job,
this keeps one per model name, so the admin margin view can say which model the money went to.
``GeminiClient._record_spend`` (the one accounting path both providers reply through) feeds
both from the same rounded price, so the per-model totals always sum to the job total.

The scope is a contextvar holding a mutable, locked accumulator, with the same semantics as
``cost_scope``: threads started under ``contextvars.copy_context().run`` share it, a bare
``threading.Thread`` does not, an inner scope shadows an outer one, and nothing here raises for
a missing scope.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

#: ``usage_job_model_costs.model`` is ``VARCHAR(128)``; a longer name is cut to this.
MODEL_NAME_MAX_LENGTH = 128


class ModelCostAccumulator:
    """A thread-safe running total of USD spent, per model name."""

    __slots__ = ("_lock", "_totals")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._totals: dict[str, Decimal] = {}

    def add(self, model: str, cost_usd: Decimal) -> None:
        """Add one call's cost under ``model``. Refuses a negative or non-finite amount."""
        if not cost_usd.is_finite() or cost_usd < 0:
            raise ValueError(f"LLM cost must be finite and non-negative: {cost_usd!r}")
        key = model[:MODEL_NAME_MAX_LENGTH]
        with self._lock:
            self._totals[key] = self._totals.get(key, Decimal(0)) + cost_usd

    def totals(self) -> dict[str, Decimal]:
        """A snapshot of USD per model, leaving out a model that cost nothing."""
        with self._lock:
            return {model: cost for model, cost in self._totals.items() if cost > 0}


_current: contextvars.ContextVar[ModelCostAccumulator | None] = contextvars.ContextVar(
    "lemely_llm_model_cost", default=None
)


@contextlib.contextmanager
def model_cost_scope() -> Iterator[ModelCostAccumulator]:
    """Collect every :func:`record_model_cost` made in this context until exit."""
    accumulator = ModelCostAccumulator()
    token = _current.set(accumulator)
    try:
        yield accumulator
    finally:
        _current.reset(token)


def record_model_cost(model: str, cost_usd: Decimal) -> None:
    """Add ``cost_usd`` to ``model`` in the innermost open scope; a no-op outside any scope."""
    accumulator = _current.get()
    if accumulator is not None:
        accumulator.add(model, cost_usd)
