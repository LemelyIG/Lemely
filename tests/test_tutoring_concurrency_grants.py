"""Races on data grants (THREAT-MODEL §7, SPEC §e.4, §a.4b; PLAN T14).

* **Revoke vs T20.** T20's validity check locks the live grant row ``FOR SHARE``
  in the transaction that writes its audit row, so a revoke still in flight is
  waited for: once a revoke has committed, no T20 read succeeds, and every read
  that did succeed has exactly one audit row (a failed or refused read has none).
  The first test makes the interleaving deterministic (a revoke held open while
  T20 queues behind it); the second runs readers and a revoker together from a
  barrier and checks the same invariant over every outcome.
* **Concurrent grants.** Grant creation takes the pair advisory lock after the
  tutor row (SPEC §a.4b), so N simultaneous S9 calls make one grant: one
  ``created``, the rest return it, and the parents' email is queued once.
* **No deadlock with a booking create.** A create holds the student's ``users``
  row ``FOR UPDATE`` and then waits for the pair lock (§a.4b steps 2, 3). S9 and
  T20 insert rows that reference that student, and the foreign-key check takes
  ``KEY SHARE`` on the row; taken late, behind the pair lock (S9) or the live grant
  row (T20), it closes a cycle. Both take ``FOR KEY SHARE`` on the student first.
  The two tests hold a create's locks by hand, queue the grant path behind them,
  then take the pair lock, so the old order deadlocks every time (40P01), not
  once in a while.

Each race runs once here; the lead's RACE loop runs the file five times at I4.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.booking_repo import lock_pair_in_session
from lemely.db.tutor_grant_repo import (
    AccessEnded,
    GrantAccess,
    GrantCreated,
    GrantRevoked,
    TutorGrantRepository,
    TutorNotListed,
)
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.test_tutor_grant_repo import (
    add_grant,
    add_student,
    audit_rows,
    link_parent,
    live_grant_count,
    outbox_rows,
    spec_pair_lock_key_sql,
)
from tests.test_tutoring_concurrency_reviews import run_together
from tests.tutoring_db import add_tutor, emptied_after, tutoring_database

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

READERS = 4
READS_AFTER_REVOKE = 3
#: Bound on every wait below; a deadlock is detected after ``deadlock_timeout`` (1 s).
WAIT_SECONDS = 10.0


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def repo(sm: sessionmaker[Session]) -> TutorGrantRepository:
    return TutorGrantRepository(sm)


def _lock_waiters(sm: sessionmaker[Session]) -> int:
    """How many backends of the test database are blocked by another backend's lock."""
    with sm() as session:
        return int(
            session.execute(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND pg_blocking_pids(pid) <> '{}'"
                )
            ).scalar_one()
        )


def _wait_for(condition: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    pytest.fail(f"timed out waiting until {what}")


def _hold_a_booking_creates_first_locks(
    holder: Session, tutor_profile_id: uuid.UUID, student: uuid.UUID
) -> None:
    """SPEC §a.4b steps 1 and 2 as ``BookingService.create`` takes them."""
    holder.execute(
        sa.text("SELECT 1 FROM tutor_profiles WHERE id = :t FOR SHARE"), {"t": tutor_profile_id}
    )
    holder.execute(sa.text("SELECT 1 FROM users WHERE id = :s FOR UPDATE"), {"s": student})


def test_t20_waits_for_an_inflight_revoke_and_then_refuses(
    sm: sessionmaker[Session], repo: TutorGrantRepository
) -> None:
    """Deterministic half, and the real proof of the ``FOR SHARE``: T20 queues, then 403.

    Without the share lock T20 would not queue at all (it would read the row as
    still live and answer 200), so the wait below fails. The race test that follows
    passes even without it, because a read that starts after the revoke commits is
    refused anyway.
    """
    tutor = add_tutor(sm)
    student = add_student(sm)
    grant = add_grant(sm, student, tutor)
    holder = sm()
    try:
        holder.execute(
            sa.text(
                "UPDATE tutor_data_grants SET revoked_at = now(), revoke_reason = 'student' "
                "WHERE id = :g"
            ),
            {"g": grant},
        )
        reader = _Paused(lambda: repo.require_valid_grant(tutor.profile_id, student))
        _wait_until_a_backend_waits_on_a_lock(sm)
        assert audit_rows(sm) == []  # queued, nothing written
        holder.commit()
    finally:
        holder.close()
    reader.join()

    assert isinstance(reader.error, AccessEnded)
    assert audit_rows(sm) == []


def test_race_revoke_vs_t20_no_200_after_revoke_commit(
    sm: sessionmaker[Session], repo: TutorGrantRepository
) -> None:
    """The invariant over free interleavings (the ``FOR SHARE`` is proved by the test above)."""
    tutor = add_tutor(sm)
    student = add_student(sm)
    grant = add_grant(sm, student, tutor)
    outcomes: list[tuple[float, str]] = []
    lock = threading.Lock()
    revoked_at: list[float] = []

    def record(started: float, outcome: str) -> None:
        with lock:
            outcomes.append((started, outcome))

    def read_once() -> str:
        started = time.monotonic()
        try:
            result = repo.require_valid_grant(tutor.profile_id, student)
        except AccessEnded:
            record(started, "403")
            return "403"
        assert isinstance(result, GrantAccess)
        record(started, "200")
        return "200"

    def reader() -> None:
        # Read until the revoke has committed, then a few more times.
        after = 0
        deadline = time.monotonic() + 20
        while after < READS_AFTER_REVOKE and time.monotonic() < deadline:
            read_once()
            if revoked_at:
                after += 1
            time.sleep(0.002)  # gaps between share locks, so the revoke is never starved

    def revoker() -> None:
        time.sleep(0.05)  # let the readers get going
        repo.revoke(student, grant)
        revoked_at.append(time.monotonic())

    # Every reader sees the grant valid before the race starts (non-vacuity).
    for _ in range(READERS):
        assert read_once() == "200"

    errors = run_together(*([reader] * READERS), revoker)

    assert errors == [None] * (READERS + 1)
    assert revoked_at, "the revoke never committed"
    committed = revoked_at[0]
    late_successes = [s for s, outcome in outcomes if outcome == "200" and s >= committed]
    assert late_successes == []
    after_commit = [s for s, _ in outcomes if s >= committed]
    assert len(after_commit) >= READERS  # every reader really did read after the commit
    successes = sum(1 for _, outcome in outcomes if outcome == "200")
    assert successes >= READERS
    assert len(audit_rows(sm)) == successes  # audit rows equal 200 responses
    assert all(row[4] == "detail" for row in audit_rows(sm))


def test_race_concurrent_grants_make_one_grant(
    sm: sessionmaker[Session], repo: TutorGrantRepository
) -> None:
    tutor = add_tutor(sm)
    student = add_student(sm)
    parent = link_parent(sm, student)
    results: list[object] = []
    lock = threading.Lock()

    def create() -> None:
        outcome = repo.create(student, tutor.profile_id)
        with lock:
            results.append(outcome)

    errors = run_together(*([create] * 8))

    assert errors == [None] * 8
    assert len(results) == 8
    created = [r for r in results if r.created]  # type: ignore[attr-defined]
    assert len(created) == 1
    assert {r.grant.id for r in results} == {created[0].grant.id}  # type: ignore[attr-defined]
    assert live_grant_count(sm, student, tutor.profile_id) == 1
    assert outbox_rows(sm) == [
        (parent, "tutor_access_granted", f"grant:{created[0].grant.id}:created:{parent}")
    ]


def test_grant_create_waits_for_a_sweep_holding_the_tutor_row(
    sm: sessionmaker[Session], repo: TutorGrantRepository
) -> None:
    """§a.4b: a suspension holds the tutor row ``FOR UPDATE``; a grant made behind it is refused."""
    tutor = add_tutor(sm)
    student = add_student(sm)
    holder = sm()
    try:
        holder.execute(
            sa.text("SELECT 1 FROM tutor_profiles WHERE id = :t FOR UPDATE"),
            {"t": tutor.profile_id},
        )
        holder.execute(
            sa.text("UPDATE tutor_profiles SET listing_state = 'suspended' WHERE id = :t"),
            {"t": tutor.profile_id},
        )
        creator = _Paused(lambda: repo.create(student, tutor.profile_id))
        _wait_until_a_backend_waits_on_a_lock(sm)
        holder.commit()
    finally:
        holder.close()
    creator.join()

    assert isinstance(creator.error, TutorNotListed)
    assert creator.error.code == "not_found"  # O11: the route answers SP2's 404
    assert live_grant_count(sm, student, tutor.profile_id) == 0


def test_grant_writes_queue_behind_the_spec_pair_lock(
    sm: sessionmaker[Session], repo: TutorGrantRepository
) -> None:
    """S9 and S10 take the pair lock keyed as SPEC §a.4b prints it (not some other key)."""
    tutor = add_tutor(sm)
    student = add_student(sm)
    params = {"student_id": student, "tutor_profile_id": tutor.profile_id}

    def behind_the_spec_lock(write: Callable[[], object]) -> object:
        holder = sm()
        try:
            holder.execute(
                sa.text(f"SELECT pg_advisory_xact_lock({spec_pair_lock_key_sql()})"), params
            )
            worker = _Paused(write)
            _wait_until_a_backend_waits_on_a_lock(sm)  # fails unless the write queued
            holder.commit()
        finally:
            holder.close()
        worker.join()
        assert worker.error is None, repr(worker.error)
        return worker.result

    created = behind_the_spec_lock(lambda: repo.create(student, tutor.profile_id))
    assert isinstance(created, GrantCreated)
    assert created.created is True
    revoked = behind_the_spec_lock(lambda: repo.revoke(student, created.grant.id))
    assert isinstance(revoked, GrantRevoked)
    assert revoked.revoked_now is True
    assert live_grant_count(sm, student, tutor.profile_id) == 0


def test_grant_create_does_not_deadlock_with_a_booking_create(
    sm: sessionmaker[Session], repo: TutorGrantRepository
) -> None:
    """Two-way cycle: create holds the student row and wants the pair lock; S9 the reverse."""
    tutor = add_tutor(sm)
    student = add_student(sm)
    holder_errors: list[BaseException] = []
    holder = sm()
    try:
        _hold_a_booking_creates_first_locks(holder, tutor.profile_id, student)
        creator = _Paused(lambda: repo.create(student, tutor.profile_id))
        _wait_until_a_backend_waits_on_a_lock(sm)  # S9 is queued behind the student row
        try:
            # Step 3 of the create. With the student row taken first, S9 holds no pair lock
            # yet, so this returns at once; taken late, it closes the cycle.
            lock_pair_in_session(holder, student_id=student, tutor_profile_id=tutor.profile_id)
            holder.commit()
        except sa.exc.DBAPIError as exc:  # the deadlock victim may be either side
            holder_errors.append(exc)
            holder.rollback()
    finally:
        holder.close()
    creator.join()

    assert holder_errors == []
    assert creator.error is None, repr(creator.error)
    assert isinstance(creator.result, GrantCreated)
    assert creator.result.created is True
    assert live_grant_count(sm, student, tutor.profile_id) == 1


def test_t20_does_not_deadlock_with_a_revoke_and_a_booking_create(
    sm: sessionmaker[Session], repo: TutorGrantRepository
) -> None:
    """Three-way cycle: T20 -> create (student row) -> revoke (pair lock) -> T20 (grant row).

    T20 takes the student row before the live grant row, so it holds nothing the
    revoke needs while it waits: the revoke commits, the create takes the pair lock,
    and T20 then finds the grant ended (403, no audit row), never a 40P01 (which it
    would report as a 500).
    """
    tutor = add_tutor(sm)
    student = add_student(sm)
    grant = add_grant(sm, student, tutor)
    revoke_done = threading.Event()

    def revoke() -> object:
        try:
            return repo.revoke(student, grant)
        finally:
            revoke_done.set()

    holder_errors: list[BaseException] = []
    holder = sm()
    try:
        _hold_a_booking_creates_first_locks(holder, tutor.profile_id, student)
        reader = _Paused(lambda: repo.require_valid_grant(tutor.profile_id, student))
        _wait_for(lambda: _lock_waiters(sm) >= 1, "T20 queued behind the student row")
        revoker = _Paused(revoke)
        # Fixed order: the revoke runs to its commit. Old order: it queues behind T20's
        # share lock on the grant row while holding the pair lock.
        _wait_for(
            lambda: revoke_done.is_set() or _lock_waiters(sm) >= 2,
            "the revoke committed or queued",
        )
        try:
            lock_pair_in_session(holder, student_id=student, tutor_profile_id=tutor.profile_id)
            holder.commit()
        except sa.exc.DBAPIError as exc:  # the deadlock victim may be any side
            holder_errors.append(exc)
            holder.rollback()
    finally:
        holder.close()
    reader.join()
    revoker.join()

    assert holder_errors == []
    assert revoker.error is None, repr(revoker.error)
    assert isinstance(revoker.result, GrantRevoked)
    assert revoker.result.revoked_now is True
    assert isinstance(reader.error, AccessEnded), repr(reader.error)
    assert audit_rows(sm) == []
