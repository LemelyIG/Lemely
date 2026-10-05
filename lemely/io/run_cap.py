"""One marking run at a time in this process (#260, #271; owner decision, 2026-10-05).

A *run* is the part of answer extraction that holds a scan's rendered pages
in the web process: from :func:`~lemely.io.rasterise.rasterise_scan_to_pages`
returning them, through ``scan_hygiene`` on each page and every Gemini call
that reads them (the extraction, the optional second read, the re-reads),
until :meth:`~lemely.io.answer_extraction.GeminiAnswerExtractor.__call__`
returns and lets them go. At worst that is 959 MiB (458 MiB of ten 16 Mpx
pages plus 501 MiB of ``scan_hygiene`` on one of them), and the 2 GiB instance
has room for one, with the owner's accepted shortfall (``docs/ci-cd.md``,
"Memory budget"). The extraction worker renders one scan
at a time, but nothing else bounded how many sets of pages the web process
held: the teacher pool and every student SSE request each ran their own.

:func:`marking_run_slot` is the cap. ``GeminiAnswerExtractor.__call__`` is the
only code that calls ``rasterise_scan_to_pages`` outside the render workers,
and every marking path reaches it: teacher grading jobs, student
corrections (both through ``lemely.web.services.grading.extract_answers``),
the accuracy harness, the CLI and the Gradio app. So one process-wide
semaphore around its body caps them all, whoever calls.

A second run WAITS for the slot, with no timeout: the queue never fails a
paper. While it waits, it publishes :attr:`EventType.EXTRACTION_QUEUED` on the
bus, scoped to its own run, so a student's SSE stream says why nothing is
moving, and again every :data:`QUEUED_HEARTBEAT_SECONDS`, so that stream (Cloud
Run cuts a request at 300 s) and a teacher's row (``updated_at`` is its
liveness; a row silent for 900 s is reported as a lost run) hear from the run
at least once a minute however long it waits. When the slot is taken it publishes
:attr:`EventType.EXTRACTION_DEQUEUED`, again once and only for a run that
waited, so the "waiting" state clears at once and not on the run's next event,
which comes after the scan render. The slot is released on every exit from the run: a
return, any exception (``BaseException`` included, so a ``KeyboardInterrupt``
or ``SystemExit`` too) and, since a thread cannot be cancelled, the end of a
run whose client has gone (an SSE stream closed mid-run keeps its worker
thread to the end, ``lemely.web.sse``) or whose awaiting task was cancelled.

The cap is per process. The container runs one web process
(``python -m lemely.web``), so it is per instance there.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from typing import TYPE_CHECKING

import structlog

from lemely.runtime.events import EventType, bus

if TYPE_CHECKING:
    from collections.abc import Iterator

log = structlog.get_logger(__name__)

#: How many runs may hold their pages at once (owner decision, 2026-10-05:
#: keep 2 GiB and cap runs at one). Each run costs up to 959 MiB of the
#: web process; ``tests/test_sandbox.py`` pins the budget this is part of.
MAX_CONCURRENT_RUNS = 1

#: How long a waiting run goes without a sign of life: it publishes
#: :attr:`EventType.EXTRACTION_QUEUED` again each time this many seconds pass
#: without the slot. Well inside the teacher console's 900 s lost-run window
#: and Cloud Run's 300 s request timeout. A module constant so tests can
#: shorten it.
QUEUED_HEARTBEAT_SECONDS = 60.0

#: The ``message`` of the :attr:`EventType.EXTRACTION_QUEUED` frame: what a
#: student sees while their paper waits for the run ahead of it.
RUN_QUEUED_MESSAGE = "Waiting for another paper to finish. Yours will start by itself."

#: The ``message`` of the :attr:`EventType.EXTRACTION_DEQUEUED` frame: what a
#: student sees once their paper has the slot and the read begins.
RUN_DEQUEUED_MESSAGE = "Reading your answers"

_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)


@contextlib.contextmanager
def marking_run_slot() -> Iterator[None]:
    """Hold one of this process's :data:`MAX_CONCURRENT_RUNS` run slots for the block.

    Takes a free slot at once. Otherwise publishes
    :attr:`EventType.EXTRACTION_QUEUED` (with :data:`RUN_QUEUED_MESSAGE`) and
    waits, for as long as it takes, for the run ahead to end, publishing it
    again every :data:`QUEUED_HEARTBEAT_SECONDS`; then publishes
    :attr:`EventType.EXTRACTION_DEQUEUED` (with :data:`RUN_DEQUEUED_MESSAGE`).
    A run that took a free slot publishes neither. The slot is given back
    however the block ends, including when a subscriber raises on the
    dequeue publish.
    """
    queued_at: float | None = None
    if not _slots.acquire(blocking=False):
        queued_at = time.monotonic()
        log.info("marking_run_queued", in_flight=MAX_CONCURRENT_RUNS)
        bus.publish(EventType.EXTRACTION_QUEUED, message=RUN_QUEUED_MESSAGE)
        while not _slots.acquire(timeout=QUEUED_HEARTBEAT_SECONDS):
            bus.publish(EventType.EXTRACTION_QUEUED, message=RUN_QUEUED_MESSAGE)
    try:
        if queued_at is not None:
            log.info("marking_run_dequeued", waited_seconds=round(time.monotonic() - queued_at, 3))
            bus.publish(EventType.EXTRACTION_DEQUEUED, message=RUN_DEQUEUED_MESSAGE)
        yield
    finally:
        _slots.release()


def _forget_after_fork() -> None:
    """In a forked child: the parent's runs are not ours, nor a slot one held."""
    global _slots
    _slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_forget_after_fork)
