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
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


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
    WARNING = "warning"
    ERROR = "error"
    DONE = "done"


class Event:
    __slots__ = ("payload", "type")

    def __init__(self, type: EventType, payload: dict[str, Any]) -> None:
        """Initialise an event with a type and free-form payload."""
        self.type = type
        self.payload = payload

    def __repr__(self) -> str:
        """Return a developer-readable representation."""
        return f"Event({self.type.value}, {self.payload!r})"


class EventBus:
    """Thread-safe publish/subscribe bus backed by simple queues.

    Subscribers receive copies of every event published after they subscribe.
    Use ``subscribe_queue`` / ``unsubscribe_queue`` to manage subscriptions; the
    returned ``queue.SimpleQueue`` is safe to drain from any thread.
    """

    def __init__(self) -> None:
        """Initialise an empty bus with no subscribers."""
        self._lock = threading.Lock()
        self._queues: list[queue.SimpleQueue[Event | None]] = []
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

    def subscribe_queue(self) -> queue.SimpleQueue[Event | None]:
        """Return a new queue that will receive all subsequent published events."""
        q: queue.SimpleQueue[Event | None] = queue.SimpleQueue()
        with self._lock:
            self._queues.append(q)
        return q

    def unsubscribe_queue(self, q: queue.SimpleQueue[Event | None]) -> None:
        """Remove a queue; silently ignored if already removed."""
        with self._lock, contextlib.suppress(ValueError):
            self._queues.remove(q)

    def publish(self, event_type: EventType, **payload: Any) -> None:  # noqa: ANN401
        """Publish an event to all current subscribers."""
        event = Event(event_type, payload)
        with self._lock:
            queues = list(self._queues)
            callbacks = list(self._callbacks.get(event_type, []))
        for q in queues:
            q.put(event)
        for cb in callbacks:
            cb(**payload)

    def publish_done(self) -> None:
        """Publish a sentinel ``None`` to signal end-of-stream to all subscribers."""
        with self._lock:
            queues = list(self._queues)
        for q in queues:
            q.put(None)


# Module-level singleton — import this in all publishers and consumers.
bus: EventBus = EventBus()
