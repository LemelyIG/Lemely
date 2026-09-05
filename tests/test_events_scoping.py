"""Per-run scoping on the process-global bus (spec §4.5, DS10)."""

from __future__ import annotations

import contextvars
import threading

from lemely.runtime.events import EventBus, EventType, current_run_id


def _drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except Exception:  # noqa: BLE001 — queue.Empty
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


def test_child_threads_must_copy_context() -> None:
    """The rule the spec pins: a bare Thread does not inherit the run id; copy_context does."""
    seen: list[str | None] = []
    token = current_run_id.set("run-1")
    try:
        t1 = threading.Thread(target=lambda: seen.append(current_run_id.get()))
        t1.start(); t1.join()
        ctx = contextvars.copy_context()
        t2 = threading.Thread(target=ctx.run, args=(lambda: seen.append(current_run_id.get()),))
        t2.start(); t2.join()
    finally:
        current_run_id.reset(token)
    assert seen == [None, "run-1"]
