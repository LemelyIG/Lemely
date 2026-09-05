"""In-process event bus for real-time UI and logging integration.

The module-level ``bus`` singleton is the single point of truth. All Lemely IO
components publish events here; the Gradio UI subscribes via queue-based
subscriptions that can be safely drained from a generator callback.

Event payloads are plain dicts — no required schema — so consumers only read
what they care about.
"""

from __future__ import annotations

import contextlib
import queue
import threading
from collections import defaultdict
from contextvars import ContextVar
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

current_run_id: ContextVar[str | None] = ContextVar("lemely_current_run_id", default=None)
"""The run (SSE stream or grading job) the current thread is working for.
Set once at the top of a worker thread; child threads must run under
``contextvars.copy_context()`` — threads do not inherit it otherwise."""


class EventType(StrEnum):
    """Identifiers for all in-process events the bus may carry."""

    GEMINI_CALL_START = "gemini_call_start"
    GEMINI_CALL_END = "gemini_call_end"
    GEMINI_CACHE_HIT = "gemini_cache_hit"
    GEMINI_RETRY = "gemini_retry"
    GEMINI_ESCALATE = "gemini_escalate"
    EXTRACTION_PROGRESS = "extraction_progress"
    MARKING_PROGRESS = "marking_progress"
    MARK_SCHEME_PROGRESS = "mark_scheme_progress"
    BUDGET_WARNING = "budget_warning"
    BUDGET_EXCEEDED = "budget_exceeded"
    WARNING = "warning"
    ERROR = "error"
    DONE = "done"


class Event:
    __slots__ = ("payload", "run_id", "type")

    def __init__(self, type: EventType, payload: dict[str, Any], run_id: str | None = None) -> None:
        """Initialise an event with a type, free-form payload, and optional run scope."""
        self.type = type
        self.payload = payload
        self.run_id = run_id

    def __repr__(self) -> str:
        """Return a developer-readable representation."""
        return f"Event({self.type.value}, {self.payload!r})"


class EventBus:
    """Thread-safe publish/subscribe bus backed by simple queues.

    Subscribers receive copies of every event published after they subscribe.
    Use ``subscribe_queue`` / ``unsubscribe_queue`` to manage subscriptions; the
    returned ``queue.SimpleQueue`` is safe to drain from any thread.

    Each queue is scoped to a run id (``subscribe_queue(run_id=...)``) or left
    unscoped (``subscribe_queue()``, the default). ``publish`` stamps every
    event with :data:`current_run_id`; a scoped queue receives events matching
    its own run id plus events published with no run id (outside any run — the
    CLI's ``BUDGET_*`` events, for instance). An unscoped queue receives
    everything, which is what ``lemely/app/live_log.py`` (Gradio) and process-
    wide listeners expect.
    """

    def __init__(self) -> None:
        """Initialise an empty bus with no subscribers."""
        self._lock = threading.Lock()
        self._queues: list[tuple[queue.SimpleQueue[Event | None], str | None]] = []
        self._callbacks: dict[EventType, list[Callable[..., Any]]] = defaultdict(list)

    def subscribe(self, event_type: EventType, callback: Callable[..., Any]) -> None:
        """Register a callback invoked synchronously for each matching published event.

        The callback receives the event payload as keyword arguments, matching the
        ``publish(**payload)`` signature. Not safe for concurrent subscribe/unsubscribe
        during publish; intended for test spies and lightweight listeners.
        """
        with self._lock:
            self._callbacks[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable[..., Any]) -> None:
        """Remove a previously registered callback; silently ignored if not found."""
        with self._lock, contextlib.suppress(ValueError):
            self._callbacks[event_type].remove(callback)

    def subscribe_queue(self, run_id: str | None = None) -> queue.SimpleQueue[Event | None]:
        """Return a new queue scoped to ``run_id`` (or unscoped, receiving everything).

        A scoped queue receives events whose ``run_id`` equals ``run_id``, plus
        events published with no run id. Pass no ``run_id`` for a queue that
        receives every event regardless of scope.
        """
        q: queue.SimpleQueue[Event | None] = queue.SimpleQueue()
        with self._lock:
            self._queues.append((q, run_id))
        return q

    def unsubscribe_queue(self, q: queue.SimpleQueue[Event | None]) -> None:
        """Remove a queue by identity; silently ignored if already removed.

        Removes *every* identity-match, where the previous ``list.remove``
        removed only the first. Unreachable through this class's own API —
        :meth:`subscribe_queue` mints a fresh ``SimpleQueue`` per call, so no
        queue can appear twice — but the two are not equivalent if a caller
        ever inserts one itself.
        """
        with self._lock:
            self._queues[:] = [entry for entry in self._queues if entry[0] is not q]

    def publish(self, event_type: EventType, **payload: Any) -> None:  # noqa: ANN401
        """Publish an event, stamped with :data:`current_run_id`, to matching subscribers."""
        event = Event(event_type, payload, run_id=current_run_id.get())
        with self._lock:
            queues = list(self._queues)
            callbacks = list(self._callbacks.get(event_type, []))
        for q, scope in queues:
            if scope is None or event.run_id is None or scope == event.run_id:
                q.put(event)
        for cb in callbacks:
            cb(**payload)

    def publish_done(self) -> None:
        """Publish the sentinel ``None`` to queues scoped to the current run, plus unscoped ones."""
        run_id = current_run_id.get()
        with self._lock:
            queues = list(self._queues)
        for q, scope in queues:
            if scope is None or scope == run_id:
                q.put(None)


# Module-level singleton — import this in all publishers and consumers.
bus: EventBus = EventBus()
