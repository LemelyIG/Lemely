"""Behavioural regression net for the soft-delete criterion (Task 4).

``test_soft_delete_criteria.py`` proves the loader criterion itself catches
every SQL shape it claims to. This module proves the claim that matters to a
real caller: every reader in ``lemely/db`` that a student's own paper-deletion
touches -- the seat roster's recency signal, the weakness-driven study-plan,
practice, and flashcard readers, the platform-admin boundary-source counts,
the teacher review queue, and the history store -- excludes a soft-deleted
``Attempt`` when called through *its own* public (or, where noted, narrowest
real private) function, never through ``DbHistoryStore.load`` standing in for
another reader.

Each test asserts presence before the stamp and absence after, so a test that
never observed the row in the first place cannot pass vacuously.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from lemely.db.admin_repo import PlatformAdminService
from lemely.db.class_repo import ClassService
from lemely.db.flashcard_repo import FlashcardService, FlashcardUnavailableError
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, Upload, WeaknessRecord
from lemely.db.models.enums import (
    AttemptOrigin,
    BoundarySource,
    ReviewReason,
    ReviewStatus,
    Role,
)
from lemely.db.models.flashcards import DeckOrigin
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.models.orgs import ClassEnrollment, SchoolClass
from lemely.db.practice_repo import PracticeRequest, PracticeService, PracticeUnavailableReason
from lemely.db.review_repo import ReviewService
from lemely.db.seat_repo import SeatService
from lemely.db.study_plan_repo import StudyPlanService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class Seeded:
    user_id: uuid.UUID
    upload_id: uuid.UUID
    attempt_id: uuid.UUID


def _seed(
    sm: sessionmaker[Session],
    *,
    origin: AttemptOrigin = AttemptOrigin.past_paper,
    boundary_source: BoundarySource | None = None,
) -> Seeded:
    """A student, one upload, and one attempt against that upload -- all live."""
    uid = uuid.uuid4()
    upload_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
        session.flush()
        session.add(Upload(id=upload_id, user_id=uid, storage_path=f"uploads/{upload_id}.pdf"))
        session.flush()
        session.add(
            Attempt(
                id=attempt_id,
                user_id=uid,
                upload_id=upload_id,
                subject_code="0625",
                awarded_marks=30,
                maximum_marks=40,
                percentage=75.0,
                recorded_at=datetime.now(UTC),
                origin=origin,
                boundary_source=boundary_source,
            )
        )
    return Seeded(user_id=uid, upload_id=upload_id, attempt_id=attempt_id)


def _stamp(sm: sessionmaker[Session], model: type[Attempt], row_id: uuid.UUID) -> None:
    """Soft-delete one row with a Core UPDATE (not filtered: it is not a select)."""
    with sm.begin() as session:
        result = session.execute(
            sa.update(model).where(model.id == row_id).values(deleted_at=datetime.now(UTC))
        )
        assert result.rowcount == 1  # type: ignore[attr-defined]


def _add_weakness(sm: sessionmaker[Session], seeded: Seeded, *, topic: str = "Algebra") -> None:
    """One ``WeaknessRecord`` with net lost marks, tied to ``seeded.attempt_id``."""
    with sm.begin() as session:
        session.add(
            WeaknessRecord(
                user_id=seeded.user_id,
                attempt_id=seeded.attempt_id,
                topic=topic,
                lost_marks=5,
                maximum_marks=10,
                accuracy=0.5,
                question_ids=[],
            )
        )


class _DummyAccountCreator:
    """Unused by the reader under test; ``SeatService`` requires one to construct."""

    def create_student(
        self, email: str, password: str, display_name: str | None = None
    ) -> uuid.UUID:
        raise NotImplementedError


@pytest.fixture
def seeded_attempt(migrated_sessionmaker: sessionmaker[Session]) -> Seeded:
    return _seed(migrated_sessionmaker)


@pytest.fixture
def seeded_weak_attempt(migrated_sessionmaker: sessionmaker[Session]) -> Seeded:
    seeded = _seed(migrated_sessionmaker)
    _add_weakness(migrated_sessionmaker, seeded)
    return seeded


# ── seat_repo: SeatService._last_attempt_by_student ────────────────────────
# (Review amendment R7: there is no SeatRepository.last_attempt_at_for.)


def test_seat_last_attempt_by_student_drops_a_deleted_attempt(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    service = SeatService(migrated_sessionmaker, _DummyAccountCreator())

    with migrated_sessionmaker() as session:
        before = service._last_attempt_by_student(session, [seeded_attempt.user_id])
    assert before.get(seeded_attempt.user_id) is not None  # present first

    _stamp(migrated_sessionmaker, Attempt, seeded_attempt.attempt_id)

    with migrated_sessionmaker() as session:  # fresh session: no warm identity map
        after = service._last_attempt_by_student(session, [seeded_attempt.user_id])
    assert after.get(seeded_attempt.user_id) is None  # then absent


# ── study_plan_repo: StudyPlanService._weaknesses (:367) ───────────────────
# StudyPlanService.generate() also computes placement/confidence/availability
# signals and persists a plan, which would require seeding question-bank and
# quiz rows unrelated to this criterion; ``_weaknesses`` is the narrowest
# real function containing the reader at :367 (brief's own line reference).


def test_study_plan_weaknesses_drops_a_deleted_attempt(
    migrated_sessionmaker: sessionmaker[Session], seeded_weak_attempt: Seeded
) -> None:
    service = StudyPlanService(migrated_sessionmaker)

    with migrated_sessionmaker() as session:
        before = service._weaknesses(session, seeded_weak_attempt.user_id, "0625")
    assert before != []  # present first

    _stamp(migrated_sessionmaker, Attempt, seeded_weak_attempt.attempt_id)

    with migrated_sessionmaker() as session:
        after = service._weaknesses(session, seeded_weak_attempt.user_id, "0625")
    assert after == []  # then absent


# ── practice_repo: PracticeService.preview (weak_topics_only) ──────────────
# A genuinely public, cheap call: with no weak topics found, preview()
# returns the refusal immediately without touching question-bank rows.


def test_practice_preview_weak_topics_only_drops_a_deleted_attempt(
    migrated_sessionmaker: sessionmaker[Session], seeded_weak_attempt: Seeded
) -> None:
    service = PracticeService(migrated_sessionmaker)
    request = PracticeRequest(subject_code="0625", count=5, weak_topics_only=True)

    before = service.preview(seeded_weak_attempt.user_id, request)
    assert before.reason != PracticeUnavailableReason.no_weaknesses.value  # present first

    _stamp(migrated_sessionmaker, Attempt, seeded_weak_attempt.attempt_id)

    after = service.preview(seeded_weak_attempt.user_id, request)
    assert after.available is False
    assert after.reason == PracticeUnavailableReason.no_weaknesses.value  # then absent


# ── flashcard_repo: FlashcardService.create_deck(origin=weakness) ──────────


def test_flashcard_create_deck_weakness_drops_a_deleted_attempt(
    migrated_sessionmaker: sessionmaker[Session], seeded_weak_attempt: Seeded
) -> None:
    service = FlashcardService(migrated_sessionmaker)

    deck = service.create_deck(
        seeded_weak_attempt.user_id,
        subject_code="0625",
        title="Weak topics",
        origin=DeckOrigin.weakness,
    )
    assert deck.topic == "Algebra"  # present first

    _stamp(migrated_sessionmaker, Attempt, seeded_weak_attempt.attempt_id)

    with pytest.raises(FlashcardUnavailableError):  # then absent
        service.create_deck(
            seeded_weak_attempt.user_id,
            subject_code="0625",
            title="Weak topics again",
            origin=DeckOrigin.weakness,
        )


# ── admin_repo: PlatformAdminService.pipeline_health boundary-source counts ─


def test_admin_pipeline_health_boundary_counts_drop_a_deleted_attempt(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    seeded = _seed(
        migrated_sessionmaker,
        origin=AttemptOrigin.past_paper,
        boundary_source=BoundarySource.exact,
    )
    service = PlatformAdminService(migrated_sessionmaker)

    before = service.pipeline_health(exact_boundary_keys=0, subject_default_boundary_keys=0)
    assert before.boundary_source_counts.get("exact", 0) >= 1  # present first

    _stamp(migrated_sessionmaker, Attempt, seeded.attempt_id)

    after = service.pipeline_health(exact_boundary_keys=0, subject_default_boundary_keys=0)
    assert after.boundary_source_counts.get("exact", 0) == 0  # then absent


# ── review_repo: ReviewService.list_queue ───────────────────────────────────


def test_review_list_queue_drops_an_item_on_a_deleted_attempt(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    teacher_id = uuid.uuid4()
    class_id = uuid.uuid4()
    with migrated_sessionmaker.begin() as session:
        session.add(User(id=teacher_id, email=f"{teacher_id}@example.com", role=Role.teacher))
        session.flush()
        session.add(
            SchoolClass(
                id=class_id,
                teacher_id=teacher_id,
                name="Set 1",
                join_code=f"join-{class_id}",
            )
        )
        session.flush()
        session.add(ClassEnrollment(class_id=class_id, student_id=seeded_attempt.user_id))
        session.flush()
        session.add(
            ReviewQueueItem(
                attempt_id=seeded_attempt.attempt_id,
                reason=ReviewReason.manual,
                status=ReviewStatus.open,
            )
        )

    service = ReviewService(migrated_sessionmaker, ClassService(migrated_sessionmaker))

    before = service.list_queue(teacher_id, Role.teacher)
    assert [r.attempt_id for r in before.rows] == [seeded_attempt.attempt_id]  # present first

    _stamp(migrated_sessionmaker, Attempt, seeded_attempt.attempt_id)

    after = service.list_queue(teacher_id, Role.teacher)
    assert after.rows == []  # then absent


# ── history_repo: DbHistoryStore.load ───────────────────────────────────────


def test_history_store_load_drops_a_deleted_attempt(
    migrated_sessionmaker: sessionmaker[Session], seeded_attempt: Seeded
) -> None:
    store = DbHistoryStore(migrated_sessionmaker)

    before = store.load(str(seeded_attempt.user_id))
    assert [r.attempt_id for r in before.records] == [str(seeded_attempt.attempt_id)]

    _stamp(migrated_sessionmaker, Attempt, seeded_attempt.attempt_id)

    after = store.load(str(seeded_attempt.user_id))
    assert after.records == []  # then absent


# ── WeaknessRecord: unreachable except through Attempt ──────────────────────
# Review amendment R8: renamed from
# ``test_weakness_rows_are_unreachable_except_through_an_attempt``; the
# overclaiming docstring is dropped, since this cannot catch a future direct
# ``select(WeaknessRecord)`` -- it only pins today's join-based shape.


def test_weakness_join_excludes_a_deleted_attempt(
    migrated_sessionmaker: sessionmaker[Session], seeded_weak_attempt: Seeded
) -> None:
    _stamp(migrated_sessionmaker, Attempt, seeded_weak_attempt.attempt_id)
    with migrated_sessionmaker() as session:
        rows = session.scalars(
            select(WeaknessRecord).join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
        ).all()
    assert rows == []
