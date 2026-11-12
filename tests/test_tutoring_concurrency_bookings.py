"""Booking races (SPEC §a.4, §a.4b, THREAT-MODEL §7, PLAN T13).

Two kinds of proof, as in ``tests/test_tutoring_concurrency_reviews.py``:

* **barrier races** release real transactions together and check what survives: eight students
  for one slot (the exclusion constraint lets exactly one in), and a tutor's accept against a
  student's cancel inside 24 hours (the pair lock and compare-and-set let exactly one win);
* **paused races** make the dangerous interleaving certain instead of lucky. The first
  transaction is stopped inside its own work (at its first outbox write, after every lock and
  count it takes); the test then proves the second transaction is *queued behind a lock*
  (``pg_blocking_pids``) before it releases the first. Without the lock under test the second
  never queues, so the test fails rather than passing on a lucky schedule.

``test_race_pending_limit_concurrent_requests_at_most_5`` is the proof for the student's
``users`` row ``FOR UPDATE`` in create (BK-2, SC-24). ``test_race_unlink_vs_parent_booking_create``
proves both orders of a parent's request and the child unlinking them (BK-3, SPEC §i.6).
``test_race_sweep_vs_create_for_the_same_student_never_deadlocks`` proves that a suspension's or a
block's cancellations take the affected students' rows before touching a booking (§a.4b step 2).
The ``*_quota_*`` races prove the SC-15 actor locks (F30-2): one canceller's cancels, and one
requester's requests, are counted one at a time even when no §a.4b lock is shared.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.booking import MAX_PENDING_PER_STUDENT
from lemely.db import booking_repo, parent_repo
from lemely.db.booking_repo import (
    BOOKING_CREATE_QUOTA,
    CANCEL_QUOTA,
    AcceptDetails,
    Actor,
    BookingRefused,
    BookingService,
)
from lemely.db.models.enums import BookingParty
from lemely.db.models.tutoring import TutorBooking
from lemely.db.parent_repo import ParentLinkService
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.test_booking_repo import (
    LINK,
    World,
    add_booking,
    add_parent,
    add_student,
    another_tutor,
    make_world,
    request,
    slot,
)
from tests.tutoring_db import emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def service(sm: sessionmaker[Session]) -> BookingService:
    return BookingService(sm)


def run_together(*jobs: Callable[[], object]) -> list[BaseException | None]:
    """Run each job on its own thread, released together from a barrier; return their errors."""
    barrier = threading.Barrier(len(jobs))
    errors: list[BaseException | None] = [None] * len(jobs)

    def runner(index: int, job: Callable[[], object]) -> None:
        try:
            barrier.wait(timeout=10)
            job()
        except BaseException as exc:  # asserted on by the test
            errors[index] = exc

    threads = [
        threading.Thread(target=runner, args=(i, job), daemon=True) for i, job in enumerate(jobs)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), "worker thread hung"
    return errors


class PauseFirstCall:
    """Wrap a function so its first call waits for :meth:`release`; later calls pass through."""

    def __init__(self, target: Callable[..., object]) -> None:
        self._target = target
        self._lock = threading.Lock()
        self._first = True
        self.reached = threading.Event()
        self._go = threading.Event()

    def __call__(self, *args: object, **kwargs: object) -> object:
        with self._lock:
            first, self._first = self._first, False
        if first:
            self.reached.set()
            assert self._go.wait(timeout=30), "the paused transaction was never released"
        return self._target(*args, **kwargs)

    def release(self) -> None:
        self._go.set()


def live_requests(sm: sessionmaker[Session], student: uuid.UUID) -> int:
    with sm() as session:
        return int(
            session.execute(
                sa.text(
                    "SELECT count(*) FROM tutor_bookings WHERE student_id = :s "
                    "AND state = 'requested' AND starts_at > now()"
                ),
                {"s": student},
            ).scalar_one()
        )


def test_race_slot_eight_students_exactly_one_request(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    start = slot()
    rivals = [World(tutor=w.tutor, subject=w.subject, student=add_student(sm)) for _ in range(8)]
    errors = run_together(*(lambda r=r: request(service, r, starts_at=start) for r in rivals))
    winners = [error for error in errors if error is None]
    losers = [error for error in errors if error is not None]
    assert len(winners) == 1
    assert all(isinstance(e, BookingRefused) and e.code == "slot_taken" for e in losers), losers
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(TutorBooking)) == 1


def test_race_accept_vs_cancel_exactly_one_wins(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    """Inside 24 hours: accepted first, the student may no longer cancel; cancelled first, the
    tutor can no longer accept. Never both, never neither."""
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(hours=10))
    errors = run_together(
        lambda: service.transition(
            booking_id=booking,
            actor=w.tutor_actor,
            action="accept",
            accept=AcceptDetails(meeting_link=LINK),
        ),
        lambda: service.transition(booking_id=booking, actor=w.student_actor, action="cancel"),
    )
    accept_error, cancel_error = errors
    assert (accept_error is None) != (cancel_error is None), errors
    with sm() as session:
        state = session.execute(
            sa.text("SELECT state::text FROM tutor_bookings WHERE id = :b"), {"b": booking}
        ).scalar_one()
    if accept_error is None:
        assert state == "accepted"
        assert isinstance(cancel_error, BookingRefused)
        assert cancel_error.code == "cancel_window_closed"
    else:
        assert state == "cancelled"
        assert isinstance(accept_error, BookingRefused)
        assert accept_error.code == "illegal_transition"


def test_race_pending_limit_concurrent_requests_at_most_5(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(MAX_PENDING_PER_STUDENT - 1):
        add_booking(sm, w, tutor=another_tutor(sm, w.subject), starts_in=timedelta(days=2 + index))
    first_tutor, second_tutor = (another_tutor(sm, w.subject) for _ in range(2))
    pause = PauseFirstCall(booking_repo.enqueue_in_session)
    monkeypatch.setattr(booking_repo, "enqueue_in_session", pause)

    first = _Paused(
        lambda: request(service, w, tutor=first_tutor, starts_at=slot(timedelta(days=12)))
    )
    assert pause.reached.wait(timeout=30), "the first request never reached its outbox write"
    second = _Paused(
        lambda: request(service, w, tutor=second_tutor, starts_at=slot(timedelta(days=14)))
    )
    try:
        _wait_until_a_backend_waits_on_a_lock(sm)  # the second queues on the student row
    finally:
        pause.release()
        first.join()
        second.join()

    assert first.error is None, first.error
    assert isinstance(second.error, BookingRefused), second.error
    assert second.error.code == "pending_limit"
    assert live_requests(sm, w.student) == MAX_PENDING_PER_STUDENT


def test_race_unlink_vs_parent_booking_create(
    sm: sessionmaker[Session], service: BookingService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both orders. Create first: the unlink waits for the child row, then removes the link; the
    booking was made while linked. Unlink first: the create waits for the child row, then finds
    no link and is refused ``not_linked``. Neither order deadlocks (SPEC §a.4b, §i.6)."""
    links = ParentLinkService(sm)

    # Order 1: the parent's request holds the child row and the link, the unlink queues.
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    pause = PauseFirstCall(booking_repo.enqueue_in_session)
    monkeypatch.setattr(booking_repo, "enqueue_in_session", pause)
    create = _Paused(lambda: request(service, w, requester=Actor(user_id=parent, party="parent")))
    assert pause.reached.wait(timeout=30)
    unlink = _Paused(lambda: links.unlink_with_event(w.student, parent))
    try:
        _wait_until_a_backend_waits_on_a_lock(sm)
    finally:
        pause.release()
        create.join()
        unlink.join()
    assert create.error is None, create.error
    assert unlink.error is None, unlink.error
    assert unlink.result is not None
    assert links.get_child(parent, w.student) is None
    assert live_requests(sm, w.student) == 1
    monkeypatch.undo()

    # Order 2: the unlink holds the child row and the deleted link, the request queues.
    w2 = make_world(sm)
    parent2 = add_parent(sm, w2.student)
    unlink_pause = PauseFirstCall(parent_repo.enqueue_in_session)
    monkeypatch.setattr(parent_repo, "enqueue_in_session", unlink_pause)
    unlink2 = _Paused(lambda: links.unlink_with_event(w2.student, parent2))
    assert unlink_pause.reached.wait(timeout=30)
    create2 = _Paused(
        lambda: request(service, w2, requester=Actor(user_id=parent2, party="parent"))
    )
    try:
        _wait_until_a_backend_waits_on_a_lock(sm)
    finally:
        unlink_pause.release()
        unlink2.join()
        create2.join()
    assert unlink2.error is None, unlink2.error
    assert isinstance(create2.error, BookingRefused), create2.error
    assert create2.error.code == "not_linked"
    assert live_requests(sm, w2.student) == 0


def _sweep(service: BookingService, session: Session, w: World, kind: str) -> list[uuid.UUID]:
    """The caller's part of a suspension or a block (§a.4b), then the booking sweep itself."""
    session.execute(
        sa.text("SELECT 1 FROM tutor_profiles WHERE id = :t FOR UPDATE"),
        {"t": w.tutor.profile_id},
    )
    if kind == "suspension":
        return service.cancel_future_for_tutor_in_session(
            session, tutor_profile_id=w.tutor.profile_id
        )
    booking_repo.lock_pair_in_session(
        session, student_id=w.student, tutor_profile_id=w.tutor.profile_id
    )
    return service.cancel_future_for_pair_in_session(
        session,
        tutor_profile_id=w.tutor.profile_id,
        student_id=w.student,
        actor_user_id=w.tutor.user_id,  # the tutor blocks: the student is emailed
    )


@pytest.mark.parametrize("kind", ["suspension", "block"])
def test_race_sweep_vs_create_for_the_same_student_never_deadlocks(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """A sweep and a create for one student queue behind each other; they never deadlock.

    The create (with a second tutor, at the time of the student's booking with the swept tutor)
    is paused holding the student's row ``FOR UPDATE``. The sweep must then queue *before* it
    touches that booking. If it cancelled the booking first and only took the student row for
    the foreign key of the student's email, the create's student-slot exclusion check would wait
    for the half-cancelled row while the sweep waited for the student row: Postgres would kill
    one of them (``40P01``). Queued first, the create finds the booking still active and is
    refused ``student_busy``, and the sweep then cancels it.
    """
    start = slot(timedelta(days=3))
    swept = add_booking(sm, w, state="accepted", starts_at=start)
    second_tutor = another_tutor(sm, w.subject)
    pause = PauseFirstCall(booking_repo.live_pending_count_in_session)
    monkeypatch.setattr(booking_repo, "live_pending_count_in_session", pause)

    create = _Paused(lambda: request(service, w, tutor=second_tutor, starts_at=start))
    assert pause.reached.wait(timeout=30), "the create never reached its pending count"

    def sweep() -> list[uuid.UUID]:
        with sm.begin() as session:
            return _sweep(service, session, w, kind)

    sweeper = _Paused(sweep)
    try:
        _wait_until_a_backend_waits_on_a_lock(sm)  # the sweep queues on the student row
    finally:
        pause.release()
        create.join()
        sweeper.join()

    assert sweeper.error is None, sweeper.error
    assert sweeper.result == [swept]
    assert isinstance(create.error, BookingRefused), create.error
    assert create.error.code == "student_busy"
    with sm() as session:
        states = (
            session.execute(
                sa.text("SELECT state::text FROM tutor_bookings WHERE student_id = :s"),
                {"s": w.student},
            )
            .scalars()
            .all()
        )
    assert states == ["cancelled"]


# ---------------------------------------------------------------------------
# SC-15 quotas: the actor's own lock (F30-2)
# ---------------------------------------------------------------------------


def _wait_until_queued_on_key(sm: sessionmaker[Session], key: str) -> None:
    """Block until a backend waits, ungranted, on ``hashtextextended(key, 0)``'s advisory lock.

    Narrower than ``_wait_until_a_backend_waits_on_a_lock``: the second transaction must be
    queued on the actor's own key, not on a pair lock, a row or a constraint check. A bigint
    advisory key shows in ``pg_locks`` as its high half (``classid``) and low half (``objid``).
    """
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with sm() as session:
            waiting = session.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_locks l "
                    "CROSS JOIN (SELECT hashtextextended(CAST(:key AS text), 0) AS k) h "
                    "WHERE l.locktype = 'advisory' AND NOT l.granted AND l.objsubid = 1 "
                    "AND l.database = (SELECT oid FROM pg_database "
                    "WHERE datname = current_database()) "
                    "AND l.classid::bigint = (h.k >> 32) & 4294967295 "
                    "AND l.objid::bigint = h.k & 4294967295"
                ),
                {"key": key},
            )
        if waiting:
            return
        time.sleep(0.05)
    pytest.fail(f"the second transaction never queued on the advisory key {key!r}")


def cancels_in_window(sm: sessionmaker[Session], user_id: uuid.UUID) -> int:
    """Cancellations by ``user_id`` in the last 24 elapsed hours (SC-15)."""
    with sm() as session:
        return int(
            session.execute(
                sa.text(
                    "SELECT count(*) FROM tutor_bookings WHERE cancelled_by_user_id = :u "
                    "AND cancelled_at > now() - make_interval(hours => 24)"
                ),
                {"u": user_id},
            ).scalar_one()
        )


def requests_in_window(sm: sessionmaker[Session], user_id: uuid.UUID) -> int:
    """Booking requests made by ``user_id`` in the last 24 elapsed hours (SC-15)."""
    with sm() as session:
        return int(
            session.execute(
                sa.text(
                    "SELECT count(*) FROM tutor_bookings WHERE requested_by_user_id = :u "
                    "AND created_at > now() - make_interval(hours => 24)"
                ),
                {"u": user_id},
            ).scalar_one()
        )


def state_of(sm: sessionmaker[Session], booking_id: uuid.UUID) -> str:
    with sm() as session:
        return str(
            session.execute(
                sa.text("SELECT state::text FROM tutor_bookings WHERE id = :b"), {"b": booking_id}
            ).scalar_one()
        )


def _cancel_race(
    sm: sessionmaker[Session],
    service: BookingService,
    monkeypatch: pytest.MonkeyPatch,
    *,
    actor: Actor,
    first_booking: uuid.UUID,
    second_booking: uuid.UUID,
) -> None:
    """Two cancels by ``actor``; the first paused at its outbox write, after its count and UPDATE.

    The second must queue on the canceller's key; once the first commits it counts the quota
    full and is refused, and its booking is untouched.
    """
    pause = PauseFirstCall(booking_repo.enqueue_in_session)
    monkeypatch.setattr(booking_repo, "enqueue_in_session", pause)
    first = _Paused(
        lambda: service.transition(booking_id=first_booking, actor=actor, action="cancel")
    )
    assert pause.reached.wait(timeout=30), "the first cancel never reached its outbox write"
    second = _Paused(
        lambda: service.transition(booking_id=second_booking, actor=actor, action="cancel")
    )
    try:
        _wait_until_queued_on_key(sm, f"tutoring_cancel:{actor.user_id}")
    finally:
        pause.release()
        first.join()
        second.join()

    assert first.error is None, first.error
    assert isinstance(second.error, BookingRefused), second.error
    assert second.error.code == "too_many_requests"
    assert cancels_in_window(sm, actor.user_id) == CANCEL_QUOTA
    assert state_of(sm, first_booking) == "cancelled"
    assert state_of(sm, second_booking) != "cancelled"


def test_race_cancel_quota_two_tutors_at_most_10(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A student with nine cancellations today cancels two sessions with two tutors at once.

    The two cancels take different pair locks and only ``KEY SHARE`` on the student's row, so
    without the canceller's own lock (F30-2a) neither waits, both count nine, and an eleventh
    cancellation commits.
    """
    for day in range(CANCEL_QUOTA - 1):
        add_booking(
            sm,
            w,
            state="cancelled",
            starts_in=timedelta(days=5 + day),
            cancelled_at=datetime.now(UTC) - timedelta(hours=2),
            cancelled_by_user_id=w.student,
        )
    second_tutor = another_tutor(sm, w.subject)
    first_booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    second_booking = add_booking(
        sm, w, tutor=second_tutor, state="requested", starts_in=timedelta(days=3)
    )
    assert cancels_in_window(sm, w.student) == CANCEL_QUOTA - 1  # non-vacuity: one below

    _cancel_race(
        sm,
        service,
        monkeypatch,
        actor=w.student_actor,
        first_booking=first_booking,
        second_booking=second_booking,
    )


def test_race_tutor_cancel_quota_two_students_at_most_10(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tutor's burst: two students' sessions cancelled at once (F30-2a, a notice to each).

    The tutor row is only ``FOR SHARE`` and the pair locks differ, so without the canceller's
    lock both cancels count nine.
    """
    other_student = add_student(sm)
    for day in range(CANCEL_QUOTA - 1):
        add_booking(
            sm,
            w,
            state="cancelled",
            starts_in=timedelta(days=5 + day),
            cancelled_at=datetime.now(UTC) - timedelta(hours=2),
            cancelled_by_user_id=w.tutor.user_id,
            cancelled_by_party=BookingParty.tutor,
        )
    first_booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    second_booking = add_booking(
        sm, w, student=other_student, state="accepted", starts_in=timedelta(days=3)
    )
    assert cancels_in_window(sm, w.tutor.user_id) == CANCEL_QUOTA - 1  # non-vacuity

    _cancel_race(
        sm,
        service,
        monkeypatch,
        actor=w.tutor_actor,
        first_booking=first_booking,
        second_booking=second_booking,
    )


def test_race_parent_create_quota_two_children_at_most_10(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parent with nine requests today asks two tutors for two children at once (F30-2b).

    Each create holds its own child's row ``FOR UPDATE``, its own pair lock and its own link, so
    without the requester's lock neither waits, both count nine and an eleventh request commits.
    The first is paused at its outbox write, after its count and its INSERT; the second must
    queue on the requester's key, then count ten and be refused.
    """
    second_child = add_student(sm)
    parent = add_parent(sm, w.student, second_child)
    for day in range(BOOKING_CREATE_QUOTA - 1):
        add_booking(
            sm,
            w,
            state="cancelled",
            starts_in=timedelta(days=5 + day),
            requested_by=parent,
            party="parent",
        )
    assert requests_in_window(sm, parent) == BOOKING_CREATE_QUOTA - 1  # non-vacuity
    second_tutor = another_tutor(sm, w.subject)
    as_parent = Actor(user_id=parent, party="parent")
    pause = PauseFirstCall(booking_repo.enqueue_in_session)
    monkeypatch.setattr(booking_repo, "enqueue_in_session", pause)

    first = _Paused(
        lambda: request(service, w, requester=as_parent, starts_at=slot(timedelta(days=2)))
    )
    assert pause.reached.wait(timeout=30), "the first request never reached its outbox write"
    second = _Paused(
        lambda: request(
            service,
            w,
            requester=as_parent,
            student_id=second_child,
            tutor=second_tutor,
            starts_at=slot(timedelta(days=4)),
        )
    )
    try:
        _wait_until_queued_on_key(sm, f"tutoring_booking_create:{parent}")
    finally:
        pause.release()
        first.join()
        second.join()

    assert first.error is None, first.error
    assert isinstance(second.error, BookingRefused), second.error
    assert second.error.code == "too_many_requests"
    assert requests_in_window(sm, parent) == BOOKING_CREATE_QUOTA
    assert live_requests(sm, w.student) == 1
    assert live_requests(sm, second_child) == 0


@pytest.fixture
def w(sm: sessionmaker[Session]) -> World:
    return make_world(sm)
