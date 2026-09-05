"""Server-Sent Events bridge over the in-process :data:`lemely.runtime.events.bus`.

The frontend (``web/src/lib/api.ts`` → ``streamActivity``) consumes SSE streams
by splitting on blank lines, reading the ``data:`` field of each frame, and
stopping at a ``[DONE]`` sentinel. This module produces exactly that wire format
from bus :class:`Event` objects.

The bus is a synchronous, thread-based queue, so the caller's work runs on a
background thread while we drain the queue from another worker thread (via
``anyio.to_thread``) and forward each event to the async generator without
blocking the event loop.

**Per-run scoping (spec §4.5, DS10).** Each stream subscribes to a queue
scoped to its own run id — :func:`bus_event_stream`'s ``run_id`` argument, or
a fresh one minted per call — and sets
:data:`~lemely.runtime.events.current_run_id` at the top of the background
worker thread before calling ``run``. The cross-talk this module used to warn
about (every concurrent stream seeing every other stream's events) is gone:
a scoped queue only ever receives its own run's events, plus events published
with no run id at all (:meth:`~lemely.runtime.events.EventBus.publish`'s
predicate).

What remains is the caller's own responsibility:

- ``run`` must still call ``bus.publish_done()`` when it finishes, on success
  or on failure — that is what ends the stream.
- Any thread ``run`` spawns must copy the context
  (``contextvars.copy_context()``) into it. A bare ``threading.Thread`` does
  not inherit ``current_run_id``, so an event published from an uncopied
  child thread carries no run id and — by the same publish predicate that
  makes unscoped events reach every run on purpose — leaks into *every*
  concurrent run's queue. No such thread or pool exists inside
  ``lemely/io/gemini.py``, ``io/correction_ai.py`` or
  ``io/answer_extraction.py`` today, but spec §4.5 anticipates a second
  grading worker later (DS13 floats raising ``_grading_pool`` above one) —
  whoever adds one must copy the context into it, or reintroduce exactly the
  cross-talk this task removed.

On client disconnect the async generator stops being iterated, but the
background ``run`` thread is **not** cancelled — it keeps executing to
completion (it is only ``join``-ed with a short timeout in ``finally``).
``run`` callables must therefore be safe to finish after the client has gone
away.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import anyio

from lemely.runtime.events import Event, EventType, bus, current_run_id

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
    run_id: str | None = None,
) -> AsyncIterator[str]:
    r"""Run ``run`` on a background thread and stream bus events as SSE frames.

    Subscribes to a queue scoped to ``run_id`` (or a freshly minted one) *before*
    starting ``run`` so no early events are missed, then yields one SSE frame per
    published event until the ``None`` sentinel (``publish_done``) arrives,
    finishing with a ``[DONE]`` frame. ``current_run_id`` is set to the same
    scope at the top of the background thread, for the lifetime of ``run`` —
    see the module docstring for what that does and does not cover.

    Args:
        run: Zero-arg callable performing the work; it must call
            ``bus.publish_done()`` when finished (e.g. in a ``finally`` block).
        poll_seconds: Queue poll interval; bounds shutdown latency.
        run_id: Scope for this stream's subscription. Omitted (the common
            case for a stream with no natural id) mints a fresh one, so two
            calls with no ``run_id`` still never cross-talk.

    Yields:
        SSE frame strings, terminated by ``data: [DONE]\\n\\n``.
    """
    scope = run_id or uuid.uuid4().hex
    q: queue.SimpleQueue[Event | None] = bus.subscribe_queue(scope)

    def _scoped_run() -> None:
        token = current_run_id.set(scope)
        try:
            run()
        finally:
            current_run_id.reset(token)

    worker = threading.Thread(target=_scoped_run, daemon=True)
    worker.start()
    try:
        while True:
            event = await anyio.to_thread.run_sync(_drain_one, q, poll_seconds)
            if event is _DONE:
                break
            if event is _EMPTY:
                # Insurance against a severe failure mode, not a fix for one seen
                # today: every current `publish_done()` caller runs under the
                # `current_run_id` its own `_scoped_run` set, so this queue always
                # gets its sentinel in practice. But a `run` that raises before
                # reaching its `finally: bus.publish_done()`, or a future bug that
                # calls `publish_done()` outside the run's own context, delivers
                # the sentinel to unscoped queues only (`EventBus.publish_done`'s
                # predicate) — this scoped queue then never sees it and would
                # spin forever. Cloud Run raises `--max-instances` alongside this
                # task, so a handful of hung streams is enough to pin every
                # instance. Ending the stream once the worker has exited with no
                # more events queued closes that hole without weakening the
                # ordinary case: a live worker still keeps the stream open no
                # matter how long a single poll comes back empty.
                if not worker.is_alive():
                    break
                continue
            yield _format_frame(event)  # type: ignore[arg-type]
        # Drain anything queued between the last poll and the end of the loop
        # above — either the real sentinel, or (the liveness path) whatever the
        # worker published before exiting without one. The worker may still be
        # mid-`publish_done()` when the liveness check above fires, so this
        # drain is what guarantees no event is dropped on that race.
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
