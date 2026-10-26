"""Races against the block, suspension and close sweeps (THREAT-MODEL §7; SPEC §a.4b, §e.4).

A block takes the tutor row ``FOR UPDATE`` and then the pair lock; a suspension or close takes
the tutor row ``FOR UPDATE``. Every booking, note and grant write takes the tutor row
``FOR SHARE`` first, so a sweep and a write never interleave: whichever starts second runs after
the first commits, and re-reads what it guards in a later statement than the one that waited.

Each race is shown two ways:

* **Deterministic interleavings.** The write is held on the pair lock by a holder session (or the
  sweep is held open in the test's own transaction) and the other side is started behind it, so
  both orders are forced every run, never left to chance. These are the halves that go red when
  the sweep's tutor lock is weakened (PLAN T21 mutation: ``FOR SHARE`` lets a suspension commit
  around a create that is still inserting).
* **Barrier rounds.** Both sides released together, a few rounds each; the invariant is checked
  over whatever order the database chose, and any deadlock (``40P01``) surfaces as an error.

Each race runs once here; the lead's RACE loop runs the file five times at I6.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.booking_repo import (
    AcceptDetails,
    BookingRefused,
    BookingRow,
    BookingService,
    lock_pair_in_session,
)
from lemely.db.models.enums import BookingParty, BookingState, Role, TutorListingState
from lemely.db.models.tutoring import TutorProfile
from lemely.db.tutor_grant_repo import GrantCreated, TutorBlocked, TutorGrantRepository
from lemely.db.tutoring_sweeps import TutoringSweeps
from tests._concurrency import _Paused
from tests.test_booking_repo import (
    LINK,
    add_booking,
    make_world,
    notes,
    request,
    stored,
)
from tests.test_tutor_grant_repo import live_grant_count
from tests.test_tutoring_concurrency_reviews import run_together
from tests.test_tutoring_sweeps import block, block_row, blocks, student_caller
from tests.tutoring_db import add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from tests.test_booking_repo import World

ROUNDS = 3
#: Bound on every wait below; a deadlock is detected after ``deadlock_timeout`` (1 s).
WAIT_SECONDS = 10.0


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


def _wait_for_waiters(sm: sessionmaker[Session], count: int) -> None:
    """Block until ``count`` backends of the test database are queued behind another's lock."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        with sm() as session:
            waiting = int(
                session.execute(
                    sa.text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND pg_blocking_pids(pid) <> '{}'"
                    )
                ).scalar_one()
            )
        if waiting >= count:
            return
        time.sleep(0.02)
    pytest.fail(f"timed out waiting for {count} queued transaction(s)")


def _hold_pair(sm: sessionmaker[Session], w: World) -> Session:
    """A session holding the pair's advisory lock (SPEC §a.4b step 3) until it commits."""
    holder = sm()
    lock_pair_in_session(holder, student_id=w.student, tutor_profile_id=w.tutor.profile_id)
    return holder


def _active_future(sm: sessionmaker[Session], tutor_profile_id: uuid.UUID) -> int:
    with sm() as session:
        return int(
            session.execute(
                sa.text(
                    "SELECT count(*) FROM tutor_bookings WHERE tutor_profile_id = :t "
                    "AND state IN ('requested', 'accepted') AND starts_at > now()"
                ),
                {"t": tutor_profile_id},
            ).scalar_one()
        )


def _listing(sm: sessionmaker[Session], tutor_profile_id: uuid.UUID) -> TutorListingState:
    with sm() as session:
        profile = session.get(TutorProfile, tutor_profile_id)
        assert profile is not None
        return profile.listing_state


def _suspend(sm: sessionmaker[Session], w: World, admin: uuid.UUID) -> object:
    return TutoringSweeps(sm).sanction(
        w.tutor.profile_id, reason="tutor_suspended", admin_user_id=admin, note=None
    )


def _refused(error: BaseException | None, *codes: str) -> bool:
    return isinstance(error, BookingRefused) and error.code in codes


# ---------------------------------------------------------------------------
# Booking create
# ---------------------------------------------------------------------------


def test_race_block_vs_booking_create_no_active_booking_survives(
    sm: sessionmaker[Session],
) -> None:
    w = make_world(sm)
    holder = _hold_pair(sm, w)
    try:
        create = _Paused(lambda: request(BookingService(sm), w))
        _wait_for_waiters(sm, 1)  # the create holds the tutor row (share) and waits on the pair
        blocker = _Paused(lambda: block(sm, w.tutor, w.student, by="student"))
        _wait_for_waiters(sm, 2)  # the block waits behind the create's tutor lock
        holder.commit()
    finally:
        holder.close()
    create.join()
    blocker.join()
    assert create.error is None
    assert blocker.error is None
    assert isinstance(create.result, BookingRow)
    row = stored(sm, create.result.id)
    assert row.state is BookingState.cancelled
    assert row.cancelled_by_party is BookingParty.system

    for _ in range(ROUNDS):
        r = make_world(sm)
        errors = run_together(
            lambda r=r: request(BookingService(sm), r),
            lambda r=r: block(sm, r.tutor, r.student, by="student"),
        )
        assert errors[1] is None, errors
        assert errors[0] is None or _refused(errors[0], "blocked"), errors
        assert _active_future(sm, r.tutor.profile_id) == 0


def test_race_suspend_vs_booking_create_no_active_booking_survives(
    sm: sessionmaker[Session],
) -> None:
    """The mutation-proof race: a create past its tutor lock is still inserting when the
    suspension starts. ``FOR UPDATE`` makes the suspension wait for it and then cancel the new
    booking; a ``FOR SHARE`` sweep would cancel first and commit around it."""
    admin = add_user(sm, Role.platform_admin)
    w = make_world(sm)
    holder = _hold_pair(sm, w)
    try:
        create = _Paused(lambda: request(BookingService(sm), w))
        _wait_for_waiters(sm, 1)
        suspension = _Paused(lambda: _suspend(sm, w, admin))
        _wait_for_waiters(sm, 2)
        holder.commit()
    finally:
        holder.close()
    create.join()
    suspension.join()
    assert create.error is None
    assert suspension.error is None
    assert isinstance(create.result, BookingRow)
    assert _listing(sm, w.tutor.profile_id) is TutorListingState.suspended
    row = stored(sm, create.result.id)
    assert row.state is BookingState.cancelled
    assert row.cancelled_by_party is BookingParty.platform_admin
    assert _active_future(sm, w.tutor.profile_id) == 0

    for _ in range(ROUNDS):
        r = make_world(sm)
        errors = run_together(
            lambda r=r: request(BookingService(sm), r), lambda r=r: _suspend(sm, r, admin)
        )
        assert errors[1] is None, errors
        assert errors[0] is None or _refused(errors[0], "tutor_not_listed"), errors
        assert _active_future(sm, r.tutor.profile_id) == 0


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------


def _accept(sm: sessionmaker[Session], w: World, booking_id: uuid.UUID) -> BookingRow:
    return BookingService(sm).transition(
        booking_id=booking_id,
        actor=w.tutor_actor,
        action="accept",
        accept=AcceptDetails(meeting_link=LINK),
    )


def test_race_suspend_vs_accept_exactly_one_outcome(sm: sessionmaker[Session]) -> None:
    """Either the accept lands and the suspension then cancels the session, or the suspension
    lands and the accept is refused; the session never ends accepted for a suspended tutor."""
    admin = add_user(sm, Role.platform_admin)

    # Accept first: queued on the pair lock when the suspension starts.
    w = make_world(sm)
    first = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    holder = _hold_pair(sm, w)
    try:
        accept = _Paused(lambda: _accept(sm, w, first))
        _wait_for_waiters(sm, 1)
        suspension = _Paused(lambda: _suspend(sm, w, admin))
        _wait_for_waiters(sm, 2)
        holder.commit()
    finally:
        holder.close()
    accept.join()
    suspension.join()
    assert accept.error is None
    assert suspension.error is None
    assert isinstance(accept.result, BookingRow)
    assert accept.result.state == "accepted"
    assert stored(sm, first).cancelled_by_party is BookingParty.platform_admin

    # Suspension first: held open in this transaction while the accept queues on the tutor row.
    w2 = make_world(sm)
    second = add_booking(sm, w2, state="requested", starts_in=timedelta(days=2))
    held = sm()
    try:
        TutoringSweeps(sm).sweep_sanction_in_session(
            held,
            tutor_profile_id=w2.tutor.profile_id,
            reason="tutor_suspended",
            admin_user_id=admin,
            note=None,
        )
        late_accept = _Paused(lambda: _accept(sm, w2, second))
        _wait_for_waiters(sm, 1)
        held.commit()
    finally:
        held.close()
    late_accept.join()
    assert _refused(late_accept.error, "tutor_suspended")
    assert stored(sm, second).state is BookingState.cancelled

    for _ in range(ROUNDS):
        r = make_world(sm)
        booking = add_booking(sm, r, state="requested", starts_in=timedelta(days=2))
        errors = run_together(
            lambda r=r, b=booking: _accept(sm, r, b), lambda r=r: _suspend(sm, r, admin)
        )
        assert errors[1] is None, errors
        assert errors[0] is None or _refused(errors[0], "tutor_suspended"), errors
        final = stored(sm, booking)
        assert final.state is BookingState.cancelled
        assert final.cancelled_by_party is BookingParty.platform_admin


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def _post(sm: sessionmaker[Session], w: World, booking_id: uuid.UUID) -> object:
    return BookingService(sm).post_note(
        booking_id=booking_id, actor=w.tutor_actor, body="Practise question 4 again."
    )


def test_race_block_vs_note_post_no_note_after_block(sm: sessionmaker[Session]) -> None:
    # The block first: held open while a note queues on the tutor row; the note is refused.
    w = make_world(sm)
    recent = add_booking(sm, w, state="completed", starts_in=-timedelta(days=2))
    held = sm()
    try:
        assert blocks(sm).block_in_session(held, student_caller(w.student), w.tutor.profile_id)
        poster = _Paused(lambda: _post(sm, w, recent))
        _wait_for_waiters(sm, 1)
        held.commit()
    finally:
        held.close()
    poster.join()
    assert _refused(poster.error, "notes_closed")
    assert notes(sm, recent) == []

    # The note first: queued on the pair lock when the block starts. It lands, before the block
    # (its transaction began first), and the next note is refused.
    w2 = make_world(sm)
    recent2 = add_booking(sm, w2, state="completed", starts_in=-timedelta(days=2))
    holder = _hold_pair(sm, w2)
    try:
        early = _Paused(lambda: _post(sm, w2, recent2))
        _wait_for_waiters(sm, 1)
        blocker = _Paused(lambda: block(sm, w2.tutor, w2.student, by="student"))
        _wait_for_waiters(sm, 2)
        holder.commit()
    finally:
        holder.close()
    early.join()
    blocker.join()
    assert early.error is None
    assert blocker.error is None
    [note] = notes(sm, recent2)
    row = block_row(sm, w2.student, w2.tutor.user_id)
    assert row is not None
    assert note.created_at < row[0]
    with pytest.raises(BookingRefused) as refused:
        _post(sm, w2, recent2)
    assert refused.value.code == "notes_closed"

    for _ in range(ROUNDS):
        r = make_world(sm)
        booking = add_booking(sm, r, state="completed", starts_in=-timedelta(days=2))
        errors = run_together(
            lambda r=r, b=booking: _post(sm, r, b),
            lambda r=r: block(sm, r.tutor, r.student, by="student"),
        )
        assert errors[1] is None, errors
        assert errors[0] is None or _refused(errors[0], "notes_closed"), errors
        made = block_row(sm, r.student, r.tutor.user_id)
        assert made is not None
        assert all(item.created_at < made[0] for item in notes(sm, booking))


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------


def _grant(sm: sessionmaker[Session], w: World) -> GrantCreated:
    return TutorGrantRepository(sm).create(w.student, w.tutor.profile_id)


def test_race_grant_create_vs_block_grant_never_valid(sm: sessionmaker[Session]) -> None:
    # The block first: held open while S9 queues on the tutor row; S9 is refused.
    w = make_world(sm)
    held = sm()
    try:
        blocks(sm).block_in_session(held, student_caller(w.student), w.tutor.profile_id)
        sharer = _Paused(lambda: _grant(sm, w))
        _wait_for_waiters(sm, 1)
        held.commit()
    finally:
        held.close()
    sharer.join()
    assert isinstance(sharer.error, TutorBlocked)
    assert live_grant_count(sm, w.student, w.tutor.profile_id) == 0

    # S9 first: queued on the pair lock when the block starts; the block revokes what it made.
    w2 = make_world(sm)
    holder = _hold_pair(sm, w2)
    try:
        early = _Paused(lambda: _grant(sm, w2))
        _wait_for_waiters(sm, 1)
        blocker = _Paused(lambda: block(sm, w2.tutor, w2.student, by="student"))
        _wait_for_waiters(sm, 2)
        holder.commit()
    finally:
        holder.close()
    early.join()
    blocker.join()
    assert early.error is None
    assert blocker.error is None
    assert isinstance(early.result, GrantCreated)
    assert live_grant_count(sm, w2.student, w2.tutor.profile_id) == 0
    with sm() as session:
        reason = session.execute(
            sa.text("SELECT revoke_reason::text FROM tutor_data_grants WHERE student_id = :s"),
            {"s": w2.student},
        ).scalar_one()
    assert reason == "block"

    for _ in range(ROUNDS):
        r = make_world(sm)
        errors = run_together(
            lambda r=r: _grant(sm, r), lambda r=r: block(sm, r.tutor, r.student, by="student")
        )
        assert errors[1] is None, errors
        assert errors[0] is None or isinstance(errors[0], TutorBlocked), errors
        assert live_grant_count(sm, r.student, r.tutor.profile_id) == 0
