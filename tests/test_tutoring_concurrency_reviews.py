"""Races on the rating aggregate (SPEC §a.4b, SC-16, PLAN T12).

Every review change recomputes ``rating_sum``/``rating_count``/``rank_score`` from
the review rows under ``SELECT ... FOR UPDATE`` on the tutor row. Three kinds of
proof here, because a lost update needs unlucky timing and a lock test does not:

* the barrier tests run two real transactions together and compare the stored
  aggregate with the independent oracle (``expected_ratings``);
* the queue tests hold the tutor row from a third connection and show that the
  review write waits behind it, then completes once it is released;
* the ``unfinished review`` tests make the lost update deterministic: a writer
  holds the tutor row with an uncommitted review, a second writer queues behind it,
  and the first commits. The second writer must then see the first one's row.
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.enums import ModerationState
from lemely.db.models.tutoring import TutorReview
from lemely.db.tutor_review_repo import TutorReviewRepository
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.test_tutor_review_repo import (
    World,
    add_booking,
    add_student,
    expected_ratings,
    stored_ratings,
)
from tests.tutoring_db import add_subject, add_tutor, emptied_after, tutoring_database

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
def repo(sm: sessionmaker[Session]) -> TutorReviewRepository:
    return TutorReviewRepository(sm)


@pytest.fixture
def w(sm: sessionmaker[Session]) -> World:
    subject = add_subject(sm)
    return World(tutor=add_tutor(sm, subjects=(subject,)), subject=subject, student=add_student(sm))


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
        thread.join(timeout=30)
        assert not thread.is_alive(), "worker thread hung"
    return errors


def review_rows(sm: sessionmaker[Session], tutor_id: uuid.UUID) -> int:
    with sm() as session:
        return int(
            session.execute(
                sa.text("SELECT count(*) FROM tutor_reviews WHERE tutor_profile_id = :t"),
                {"t": tutor_id},
            ).scalar_one()
        )


def test_race_two_reviews_same_student_aggregate_counts_once(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    first = add_booking(sm, student=w.student, tutor=w.tutor, subject=w.subject)
    second = add_booking(
        sm,
        student=w.student,
        tutor=w.tutor,
        subject=w.subject,
        ended_ago=timedelta(days=20),
    )
    errors = run_together(
        lambda: repo.create_review(w.student, first, stars=5, text=None),
        lambda: repo.create_review(w.student, second, stars=1, text=None),
    )
    assert errors == [None, None]
    assert review_rows(sm, w.tutor.profile_id) == 2
    total, count, rank = expected_ratings(sm, w.tutor.profile_id)
    assert count == 1  # one student, however many reviews (SC-16)
    assert total in {1, 5}
    assert stored_ratings(sm, w.tutor.profile_id) == (total, count, rank)


def test_race_two_students_reviews_are_both_counted(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    """A lost update (each transaction recomputing without the other's row) leaves one student."""
    other = add_student(sm)
    first = add_booking(sm, student=w.student, tutor=w.tutor, subject=w.subject)
    second = add_booking(sm, student=other, tutor=w.tutor, subject=w.subject)
    errors = run_together(
        lambda: repo.create_review(w.student, first, stars=5, text=None),
        lambda: repo.create_review(other, second, stars=3, text=None),
    )
    assert errors == [None, None]
    assert stored_ratings(sm, w.tutor.profile_id) == (
        8,
        2,
        expected_ratings(sm, w.tutor.profile_id)[2],
    )
    assert expected_ratings(sm, w.tutor.profile_id)[:2] == (8, 2)


def test_review_create_waits_on_the_tutor_row_lock(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    booking = add_booking(sm, student=w.student, tutor=w.tutor, subject=w.subject)
    holder = sm()
    try:
        holder.execute(
            sa.text("SELECT 1 FROM tutor_profiles WHERE id = :t FOR UPDATE"),
            {"t": w.tutor.profile_id},
        )
        writer = _Paused(lambda: repo.create_review(w.student, booking, stars=4, text=None))
        _wait_until_a_backend_waits_on_a_lock(sm)
        assert review_rows(sm, w.tutor.profile_id) == 0  # queued, not written
    finally:
        holder.rollback()
        holder.close()
    writer.join()
    assert writer.error is None
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (4, 1)


def test_review_edit_waits_on_the_tutor_row_lock(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    created = repo.create_review(
        w.student,
        add_booking(sm, student=w.student, tutor=w.tutor, subject=w.subject),
        stars=4,
        text=None,
    )
    holder = sm()
    try:
        holder.execute(
            sa.text("SELECT 1 FROM tutor_profiles WHERE id = :t FOR UPDATE"),
            {"t": w.tutor.profile_id},
        )
        writer = _Paused(
            lambda: repo.update_review(
                w.student, created.review_id, stars=1, text=None, clear_text=False
            )
        )
        _wait_until_a_backend_waits_on_a_lock(sm)
        assert stored_ratings(sm, w.tutor.profile_id)[:2] == (4, 1)  # queued, not applied
    finally:
        holder.rollback()
        holder.close()
    writer.join()
    assert writer.error is None
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (1, 1)


def _hold_tutor_row_with_an_unfinished_review(
    sm: sessionmaker[Session], w: World, other: uuid.UUID
) -> Session:
    """A writer that owns the tutor row and has a review of ``other`` written but not committed.

    Every booking is seeded before this is called: inserting one needs a share lock on the tutor
    row (its foreign key), which the held ``FOR UPDATE`` would refuse.
    """
    booking = add_booking(sm, student=other, tutor=w.tutor, subject=w.subject)
    holder = sm()
    holder.execute(
        sa.text("SELECT 1 FROM tutor_profiles WHERE id = :t FOR UPDATE"), {"t": w.tutor.profile_id}
    )
    holder.execute(
        sa.insert(TutorReview).values(
            booking_id=booking,
            tutor_profile_id=w.tutor.profile_id,
            student_id=other,
            stars=3,
            text_state=ModerationState.none,
        )
    )
    return holder


def test_a_review_created_behind_an_unfinished_one_does_not_lose_it(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    """The lock comes before the write: the second writer reads the first one's committed row.

    Without it the second writer would insert, read the totals while the first is uncommitted,
    and overwrite the first one's total once that commits (a lost update).
    """
    booking = add_booking(sm, student=w.student, tutor=w.tutor, subject=w.subject)
    holder = _hold_tutor_row_with_an_unfinished_review(sm, w, add_student(sm))
    try:
        writer = _Paused(lambda: repo.create_review(w.student, booking, stars=5, text=None))
        _wait_until_a_backend_waits_on_a_lock(sm)
        repo.recompute_ratings_in_session(holder, w.tutor.profile_id)
        holder.commit()
    finally:
        holder.close()
    writer.join()
    assert writer.error is None
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (8, 2)
    assert stored_ratings(sm, w.tutor.profile_id) == expected_ratings(sm, w.tutor.profile_id)


def test_an_edit_behind_an_unfinished_review_does_not_lose_it(
    sm: sessionmaker[Session], repo: TutorReviewRepository, w: World
) -> None:
    created = repo.create_review(
        w.student,
        add_booking(sm, student=w.student, tutor=w.tutor, subject=w.subject),
        stars=4,
        text=None,
    )
    holder = _hold_tutor_row_with_an_unfinished_review(sm, w, add_student(sm))
    try:
        writer = _Paused(
            lambda: repo.update_review(
                w.student, created.review_id, stars=1, text=None, clear_text=False
            )
        )
        _wait_until_a_backend_waits_on_a_lock(sm)
        repo.recompute_ratings_in_session(holder, w.tutor.profile_id)
        holder.commit()
    finally:
        holder.close()
    writer.join()
    assert writer.error is None
    assert stored_ratings(sm, w.tutor.profile_id)[:2] == (4, 2)  # 1 star + the other student's 3
    assert stored_ratings(sm, w.tutor.profile_id) == expected_ratings(sm, w.tutor.profile_id)
