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

Each race runs once here; the lead's RACE loop runs the file five times at I4.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.tutor_grant_repo import AccessEnded, GrantAccess, TutorGrantRepository
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.test_tutor_grant_repo import (
    add_grant,
    add_student,
    audit_rows,
    link_parent,
    live_grant_count,
    outbox_rows,
)
from tests.test_tutoring_concurrency_reviews import run_together
from tests.tutoring_db import add_tutor, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

READERS = 4
READS_AFTER_REVOKE = 3


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


def test_t20_waits_for_an_inflight_revoke_and_then_refuses(
    sm: sessionmaker[Session], repo: TutorGrantRepository
) -> None:
    """Deterministic half: a revoke holding the grant row makes T20 queue, then 403."""
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

    assert creator.error is not None
    assert getattr(creator.error, "code", None) == "tutor_not_listed"
    assert live_grant_count(sm, student, tutor.profile_id) == 0
