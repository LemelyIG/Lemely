"""Server-Sent Events bridge over the in-process :data:`lemely.runtime.events.bus`.

The frontend (``web/src/lib/api.ts`` → ``streamActivity``) consumes SSE streams
by splitting on blank lines, reading the ``data:`` field of each frame, and
stopping at a ``[DONE]`` sentinel. This module produces exactly that wire format
from bus :class:`Event` objects.

The bus is a synchronous, thread-based queue, so the caller's work runs on a
background thread while we drain the queue from another worker thread (via
``anyio.to_thread``) and forward each event to the async generator without
blocking the event loop. Publishers call :meth:`EventBus.publish_done` when
finished, which enqueues the ``None`` sentinel that terminates the stream.
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any

import anyio

from lemely.runtime.events import Event, EventType, bus

# Frontend frame contract: one ``data:`` line per SSE frame, frames separated by
# a blank line, terminated by a literal ``[DONE]`` payload.
_DONE_FRAME = "data: [DONE]\n\n"

# Sentinels distinguishing "stream finished" and "poll timed out" from a real event.
_DONE: object = object()
_EMPTY: object = object()


def _event_to_payload(event: Event) -> dict[str, Any]:
    """Flatten an :class:`Event` into the JSON shape the frontend expects.

    Produces ``{"type": <event-type>, ...payload}`` — matching the
    ``ActivityEvent`` interface (a ``type`` string plus arbitrary extra keys).
    """
    payload: dict[str, Any] = {"type": event.type.value}
    payload.update(event.payload)
    return payload


def _format_frame(event: Event) -> str:
    r"""Serialise one event as a single ``data: {json}\n\n`` SSE frame."""
    return f"data: {json.dumps(_event_to_payload(event), default=str)}\n\n"


def _drain_one(q: queue.SimpleQueue[Event | None], poll_seconds: float) -> object:
    """Block-poll a single event; return ``_DONE``/``_EMPTY`` sentinels on end/timeout."""
    try:
        event = q.get(timeout=poll_seconds)
    except queue.Empty:
        return _EMPTY
    if event is None:
        return _DONE
    return event


def _drain_nowait(q: queue.SimpleQueue[Event | None]) -> Event | None:
    """Return the next queued event without blocking, or ``None`` on empty/sentinel."""
    try:
        event = q.get_nowait()
    except queue.Empty:
        return None
    return event


async def bus_event_stream(
    run: Callable[[], Any],
    *,
    poll_seconds: float = 0.15,
) -> AsyncIterator[str]:
    r"""Run ``run`` on a background thread and stream bus events as SSE frames.

    Subscribes to the global bus *before* starting ``run`` so no early events are
    missed, then yields one SSE frame per published event until the ``None``
    sentinel (``publish_done``) arrives, finishing with a ``[DONE]`` frame.

    .. warning::

       This bridges the *global*, process-wide :data:`bus`, which fans every
       published event out to all subscriber queues. As a result only **one**
       SSE stream may run at a time: two concurrent callers would each receive
       the other's events (cross-talk), because there is no per-stream event
       scoping. Serialise upload/extract/grade/correct flows accordingly until
       the bus grows per-request channels.

       On client disconnect the async generator stops being iterated, but the
       background ``run`` thread is **not** cancelled — it keeps executing to
       completion (it is only ``join``-ed with a short timeout in ``finally``).
       ``run`` callables must therefore be safe to finish after the client has
       gone away and must always call ``bus.publish_done()``.

    Args:
        run: Zero-arg callable performing the work; it must call
            ``bus.publish_done()`` when finished (e.g. in a ``finally`` block).
        poll_seconds: Queue poll interval; bounds shutdown latency.

    Yields:
        SSE frame strings, terminated by ``data: [DONE]\\n\\n``.
    """
    q: queue.SimpleQueue[Event | None] = bus.subscribe_queue()
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        while True:
            event = await anyio.to_thread.run_sync(_drain_one, q, poll_seconds)
            if event is _DONE:
                break
            if event is _EMPTY:
                continue
            yield _format_frame(event)  # type: ignore[arg-type]
        # Drain anything published between the last poll and the sentinel.
        while True:
            trailing = await anyio.to_thread.run_sync(_drain_nowait, q)
            if trailing is None:
                break
            yield _format_frame(trailing)
        yield _DONE_FRAME
    finally:
        bus.unsubscribe_queue(q)
        worker.join(timeout=poll_seconds)


__all__ = ["EventType", "bus", "bus_event_stream"]
