"""Live-log helpers for the Gradio UI.

Provides ``LiveLogBuffer``, a thread-safe ring buffer that ingests ``Event``
objects from the ``EventBus`` and formats them as human-readable log lines.
The Gradio callbacks drain it per-yield to feed the Live Activity panel.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Iterator

from lemely.runtime.events import Event, EventType, bus

_MAX_LINES = 300  # ring buffer capacity


def _format_event(event: Event) -> str:
    """Return a single display line for an event."""
    ts = time.strftime("%H:%M:%S")
    p = event.payload
    t = event.type

    if t == EventType.GEMINI_CALL_START:
        return f"{ts}  ▶  {p.get('task', '?')} · {p.get('model', '?')}"
    if t == EventType.GEMINI_CALL_END:
        return (
            f"{ts}  ✓  {p.get('task', '?')} · {p.get('model', '?')} "
            f"· {p.get('latency_ms', '?')} ms "
            f"· in={p.get('input_tokens', 0):,} out={p.get('output_tokens', 0):,} "
            f"· ${p.get('usd_cost', 0):.4f}"
        )
    if t == EventType.GEMINI_CACHE_HIT:
        return f"{ts}  ⚡ cache hit · {p.get('task', '?')} · key={p.get('cache_key', '?')[:8]}"
    if t == EventType.GEMINI_RETRY:
        return f"{ts}  ↻  retry attempt={p.get('attempt', '?')} error={p.get('error', '')[:60]}"
    if t == EventType.GEMINI_ESCALATE:
        return f"{ts}  ⬆  escalate q={p.get('question_id', '?')} → {p.get('escalation_model', '?')}"
    if t == EventType.EXTRACTION_PROGRESS:
        conf = p.get("confidence", 0)
        return f"{ts}  📄 extract q={p.get('question_id', '?')} conf={conf:.2f}"
    if t == EventType.MARKING_PROGRESS:
        return (
            f"{ts}  🖊  mark q={p.get('question_id', '?')} "
            f"src={p.get('marker_source', '?')} "
            f"conf={p.get('confidence', 0):.2f}"
        )
    if t == EventType.MARK_SCHEME_PROGRESS:
        return f"{ts}  📋 mark_scheme · {p.get('status', '?')}"
    if t == EventType.ERROR:
        return f"{ts}  ✗  error: {p.get('message', '')[:80]}"
    if t == EventType.DONE:
        return f"{ts}  ■  done"
    return f"{ts}  {t.value} {p}"  # type: ignore[unreachable]


class LiveLogBuffer:
    """Subscribe to the global EventBus and accumulate formatted log lines.

    Designed for use inside a Gradio generator callback:

        buf = LiveLogBuffer()
        buf.start()
        # ... run long operation in background thread ...
        for lines in buf.drain_until_done():
            yield lines
        buf.stop()
    """

    def __init__(self, maxlines: int = _MAX_LINES) -> None:
        self._lines: deque[str] = deque(maxlen=maxlines)
        self._q: queue.SimpleQueue[Event | None] | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Subscribe to the global bus. Call once before starting background work."""
        self._q = bus.subscribe_queue()

    def stop(self) -> None:
        """Unsubscribe from the global bus. Call after all work is complete."""
        if self._q is not None:
            bus.unsubscribe_queue(self._q)
            self._q = None

    def drain_pending(self) -> None:
        """Consume all queued events and append formatted lines to the ring buffer."""
        if self._q is None:
            return
        while True:
            try:
                event = self._q.get_nowait()
            except queue.Empty:
                break
            if event is None:
                break
            with self._lock:
                self._lines.append(_format_event(event))

    def current_text(self) -> str:
        """Return all buffered lines joined by newlines (for ``gr.Code`` / ``gr.Textbox``)."""
        with self._lock:
            return "\n".join(self._lines)

    def drain_until_done(self, poll_seconds: float = 0.15) -> Iterator[str]:
        """Block-poll the event queue, yielding the current log text after each drain.

        Stops when a ``None`` sentinel (DONE) is received or the queue is closed.
        Designed to be used with a background thread that calls ``bus.publish_done()``
        when its work is complete.
        """
        if self._q is None:
            return
        while True:
            try:
                event = self._q.get(timeout=poll_seconds)
            except queue.Empty:
                yield self.current_text()
                continue
            if event is None:
                break
            with self._lock:
                self._lines.append(_format_event(event))
            yield self.current_text()
        # Final drain after sentinel.
        self.drain_pending()
        yield self.current_text()
