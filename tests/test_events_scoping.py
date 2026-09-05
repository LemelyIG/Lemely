"""Per-run scoping on the process-global bus (spec §4.5, DS10)."""

from __future__ import annotations

import contextvars
import queue
import threading
import uuid

from lemely.runtime.events import EventBus, EventType, current_run_id


def _drain(q: queue.SimpleQueue[object]) -> list[object]:
    """Drain everything currently queued, without blocking.

    Catches only ``queue.Empty``: a broader ``except`` here would swallow a
    real failure inside the bus and report it as "no events", which is the
    one answer these tests must never get wrong.
    """
    out: list[object] = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def test_scoped_queues_do_not_cross_talk() -> None:
    bus = EventBus()
    qa, qb, q_all = bus.subscribe_queue("a"), bus.subscribe_queue("b"), bus.subscribe_queue()
    token = current_run_id.set("a")
    try:
        bus.publish(EventType.WARNING, message="from a")
    finally:
        current_run_id.reset(token)
    token = current_run_id.set("b")
    try:
        bus.publish(EventType.WARNING, message="from b")
    finally:
        current_run_id.reset(token)
    assert [e.payload["message"] for e in _drain(qa)] == ["from a"]
    assert [e.payload["message"] for e in _drain(qb)] == ["from b"]
    assert [e.payload["message"] for e in _drain(q_all)] == ["from a", "from b"]


def test_unscoped_events_reach_every_queue() -> None:
    bus = EventBus()
    qa, q_all = bus.subscribe_queue("a"), bus.subscribe_queue()
    bus.publish(EventType.BUDGET_WARNING, threshold=4.0)
    assert len(_drain(qa)) == 1 and len(_drain(q_all)) == 1


def test_sentinel_ends_only_its_own_run() -> None:
    bus = EventBus()
    qa, qb, q_all = bus.subscribe_queue("a"), bus.subscribe_queue("b"), bus.subscribe_queue()
    token = current_run_id.set("a")
    try:
        bus.publish_done()
    finally:
        current_run_id.reset(token)
    assert _drain(qa) == [None]
    assert _drain(qb) == []
    assert _drain(q_all) == [None]


def test_publish_done_with_no_current_run_id_does_not_end_other_runs() -> None:
    """The asymmetry between `publish` and `publish_done`, pinned.

    `publish` deliberately passes an unscoped event through to every queue
    (`event.run_id is None`), because a budget warning belongs to no run and
    concerns them all. `publish_done` deliberately does NOT: a sentinel from
    an unscoped context must end nothing, because the symmetric version would
    let one caller who forgot to set `current_run_id` terminate every live
    stream in the process — the exact cross-talk DS10 exists to remove.

    Without this test the suite cannot tell the two apart: every other case
    here sets `current_run_id` before publishing, so the wrong predicate
    passes them all.
    """
    bus = EventBus()
    qa, qb = bus.subscribe_queue("a"), bus.subscribe_queue("b")
    bus.publish_done()  # no current_run_id set
    assert _drain(qa) == []
    assert _drain(qb) == []


def test_a_publisher_that_forgets_its_scope_reaches_every_run() -> None:
    """`publish`'s unscoped pass-through is a loaded gun; this documents it.

    `publish` deliberately delivers an event with ``run_id is None`` to every
    queue, so that genuinely process-wide events (the CLI's ``BUDGET_*``) are
    not lost by scoped listeners. The cost is that any publisher running on a
    thread that never set :data:`current_run_id` broadcasts to all of them —
    which for a marking event means one user's per-question results arriving
    on another user's stream.

    This is asserted rather than merely warned about in a docstring, because
    the mechanism is invisible at the call site: nothing about
    ``bus.publish(...)`` hints that the surrounding thread's context decides
    who receives it. Anyone who changes this predicate should have to change
    this test, and read why.

    `lemely/web/routers/quiz.py` is the reason this is not hypothetical: it
    marks submissions on a bare daemon thread, and until it set a run id its
    marking events reached every open stream.
    """
    bus = EventBus()
    qa, qb = bus.subscribe_queue("run-a"), bus.subscribe_queue("run-b")
    bus.publish(EventType.WARNING, message="from a thread with no run id")
    assert len(_drain(qa)) == 1
    assert len(_drain(qb)) == 1


def test_a_scoped_publisher_reaches_only_its_own_run() -> None:
    """The other half: once the publisher sets a scope, the leak closes.

    This is the shape every background worker must follow — the fix applied
    to `quiz.py`'s marking thread, and what `_scoped_run` and
    `_run_grading_job` already do.
    """
    bus = EventBus()
    qa, qb = bus.subscribe_queue("run-a"), bus.subscribe_queue("run-b")
    token = current_run_id.set("run-a")
    try:
        bus.publish(EventType.WARNING, message="scoped to a")
    finally:
        current_run_id.reset(token)
    assert [e.payload["message"] for e in _drain(qa)] == ["scoped to a"]
    assert _drain(qb) == []


def test_child_threads_must_copy_context() -> None:
    """The rule the spec pins: a bare Thread does not inherit the run id; copy_context does.

    This asserts CPython's own PEP 567 semantics, not anything in
    :mod:`lemely.runtime.events` — it touches no bus method. It is kept
    deliberately, as an executable statement of the assumption every worker
    that publishes from a child thread depends on: if a Python upgrade ever
    changed it, the failure would otherwise surface as silent cross-run
    leakage rather than a red test.
    """
    seen: list[str | None] = []
    token = current_run_id.set("run-1")
    try:
        t1 = threading.Thread(target=lambda: seen.append(current_run_id.get()))
        t1.start()
        t1.join()
        ctx = contextvars.copy_context()
        t2 = threading.Thread(target=ctx.run, args=(lambda: seen.append(current_run_id.get()),))
        t2.start()
        t2.join()
    finally:
        current_run_id.reset(token)
    assert seen == [None, "run-1"]


def test_quiz_marking_thread_sets_its_run_id() -> None:
    """`quiz.py`'s fire-and-forget marking thread must scope its bus events.

    Lives here rather than in `tests/test_web_quiz.py` deliberately: that
    module needs a reachable Postgres and skips without one, and a guard
    against a cross-tenant leak should not be skippable. Nothing here touches
    the database — `_trigger_marking_in_background` only calls
    `mark_submission`, so a duck-typed double is enough to observe the
    context the thread runs under.

    Reverting the `current_run_id.set(...)` in that function fails this.
    """
    from lemely.web.routers.quiz import _trigger_marking_in_background

    submission_id = uuid.uuid4()
    seen: list[str | None] = []
    done = threading.Event()

    class _RecordingMarkingService:
        def mark_submission(self, sid: uuid.UUID) -> None:
            seen.append(current_run_id.get())
            done.set()

    _trigger_marking_in_background(_RecordingMarkingService(), submission_id)  # type: ignore[arg-type]
    assert done.wait(timeout=5.0), "the marking thread never ran"
    assert seen == [f"quiz:{submission_id}"], (
        "the marking thread published under no run id, so `EventBus.publish`'s "
        "unscoped pass-through would deliver its marking events to every open stream"
    )
