"""The student's paper deletion (design 2026-09-22 §6, §8, §13; Task 5).

Every post-delete assertion reads through a **fresh** session: the service's
own session is closed by then, and a warm identity map would otherwise answer
from memory rather than from the database (``session.py``'s documented gap).
Every refusal test also proves nothing was stamped, so a refusal that raised
after a partial write cannot pass.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from lemely.core.deletion import RETENTION_DAYS, integrity_hold_until, restore_deadline
from lemely.db.deletion_repo import (
    DeletedPaper,
    PaperDeletionService,
    PaperNotDeletableError,
    PaperNotFoundError,
    PaperNotRestorableError,
    paper_label,
)
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult, Upload
from lemely.db.models.enums import (
    AttemptOrigin,
    ConfidenceBand,
    MarkerSource,
    ReviewReason,
    ReviewStatus,
    Role,
    SessionMonth,
    UploadStatus,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.session import INCLUDE_DELETED
from tests.test_attempt_repo import _Paused, _wait_until_a_backend_waits_on_a_lock

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.orm import Session, sessionmaker

_HOLD_REFUSAL = "This paper can't be deleted yet."


@dataclass(frozen=True)
class Seeded:
    upload_id: uuid.UUID | None
    attempt_id: uuid.UUID
    recorded_at: datetime


def _seed_user(sm: sessionmaker[Session]) -> str:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    return str(uid)


def _seed_upload(sm: sessionmaker[Session], owner: str) -> uuid.UUID:
    upload_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Upload(
                id=upload_id,
                user_id=uuid.UUID(owner),
                storage_path=f"uploads/{upload_id}.pdf",
                idempotency_key=f"scan-{upload_id}",
            )
        )
    return upload_id


def _seed_attempt(
    sm: sessionmaker[Session],
    owner: str,
    upload_id: uuid.UUID | None,
    *,
    origin: AttemptOrigin = AttemptOrigin.past_paper,
    recorded_at: datetime | None = None,
) -> Seeded:
    attempt_id = uuid.uuid4()
    when = recorded_at or datetime.now(UTC)
    with sm.begin() as session:
        session.add(
            Attempt(
                id=attempt_id,
                user_id=uuid.UUID(owner),
                upload_id=upload_id,
                subject_code="0625",
                session_month=SessionMonth.may_june,
                session_year=2024,
                paper_number=4,
                paper_variant=2,
                awarded_marks=30,
                maximum_marks=40,
                percentage=75.0,
                recorded_at=when,
                origin=origin,
            )
        )
    return Seeded(upload_id=upload_id, attempt_id=attempt_id, recorded_at=when)


def _seed_question(
    sm: sessionmaker[Session],
    attempt_id: uuid.UUID,
    *,
    plagiarism: bool = False,
    ai_detection: bool = False,
    overridden_by: uuid.UUID | None = None,
) -> uuid.UUID:
    qr_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            QuestionResult(
                id=qr_id,
                attempt_id=attempt_id,
                question_id="1",
                awarded_marks=2,
                maximum_marks=4,
                confidence_band=ConfidenceBand.low,
                confidence_score=0.4,
                marker_source=MarkerSource.ai,
                plagiarism_flagged=plagiarism,
                ai_detection_flagged=ai_detection,
                teacher_awarded_marks=3 if overridden_by else None,
                overridden_by=overridden_by,
                overridden_at=datetime.now(UTC) if overridden_by else None,
            )
        )
    return qr_id


def _seed_item(
    sm: sessionmaker[Session],
    attempt_id: uuid.UUID,
    reason: ReviewReason,
    status: ReviewStatus = ReviewStatus.open,
) -> uuid.UUID:
    item_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            ReviewQueueItem(id=item_id, attempt_id=attempt_id, reason=reason, status=status)
        )
    return item_id


def _set_status(sm: sessionmaker[Session], item_id: uuid.UUID, status: ReviewStatus) -> None:
    with sm.begin() as session:
        item = session.get(ReviewQueueItem, item_id)
        assert item is not None
        item.status = status
        if status in (ReviewStatus.resolved, ReviewStatus.dismissed):
            item.resolved_at = datetime.now(UTC)


def _attempt_row(sm: sessionmaker[Session], attempt_id: uuid.UUID) -> Attempt:
    with sm() as session:
        return session.scalars(
            select(Attempt)
            .where(Attempt.id == attempt_id)
            .execution_options(**{INCLUDE_DELETED: True})
        ).one()


def _upload_row(sm: sessionmaker[Session], upload_id: uuid.UUID | None) -> Upload:
    with sm() as session:
        return session.scalars(
            select(Upload)
            .where(Upload.id == upload_id)
            .execution_options(**{INCLUDE_DELETED: True})
        ).one()


def _item_row(sm: sessionmaker[Session], item_id: uuid.UUID) -> ReviewQueueItem:
    with sm() as session:
        item = session.get(ReviewQueueItem, item_id)
        assert item is not None
        return item


def _assert_untouched(sm: sessionmaker[Session], seeded: Seeded) -> None:
    """A refusal wrote nothing: the attempt and its upload are both still live."""
    assert _attempt_row(sm, seeded.attempt_id).deleted_at is None
    upload = _upload_row(sm, seeded.upload_id)
    assert upload.deleted_at is None
    assert upload.idempotency_key is not None


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sessionmaker_(migrated_sessionmaker: sessionmaker[Session]) -> sessionmaker[Session]:
    return migrated_sessionmaker


@pytest.fixture
def service(sessionmaker_: sessionmaker[Session]) -> PaperDeletionService:
    return PaperDeletionService(sessionmaker_)


@pytest.fixture
def store(sessionmaker_: sessionmaker[Session]) -> DbHistoryStore:
    return DbHistoryStore(sessionmaker_)


@pytest.fixture
def owner(sessionmaker_: sessionmaker[Session]) -> str:
    return _seed_user(sessionmaker_)


@pytest.fixture
def stranger(sessionmaker_: sessionmaker[Session]) -> str:
    return _seed_user(sessionmaker_)


@pytest.fixture
def attempt(sessionmaker_: sessionmaker[Session], owner: str) -> Seeded:
    return _seed_attempt(sessionmaker_, owner, _seed_upload(sessionmaker_, owner))


@pytest.fixture
def open_item(sessionmaker_: sessionmaker[Session], attempt: Seeded) -> uuid.UUID:
    """An ordinary low-confidence review, still open."""
    return _seed_item(sessionmaker_, attempt.attempt_id, ReviewReason.low_confidence)


@pytest.fixture
def flagged_attempt(sessionmaker_: sessionmaker[Session], owner: str) -> Seeded:
    """Recorded now, with a plagiarism flag on one question: inside the D8 hold."""
    seeded = _seed_attempt(sessionmaker_, owner, _seed_upload(sessionmaker_, owner))
    _seed_question(sessionmaker_, seeded.attempt_id, plagiarism=True)
    return seeded


@pytest.fixture
def integrity_item(sessionmaker_: sessionmaker[Session], flagged_attempt: Seeded) -> uuid.UUID:
    return _seed_item(sessionmaker_, flagged_attempt.attempt_id, ReviewReason.plagiarism_flag)


# ── the delete itself ───────────────────────────────────────────────────────


def test_delete_hides_the_paper_from_the_students_history(
    service: PaperDeletionService, store: DbHistoryStore, owner: str, attempt: Seeded
) -> None:
    assert [r.attempt_id for r in store.load(owner).records] == [str(attempt.attempt_id)]
    service.delete(owner, str(attempt.attempt_id))
    assert store.load(owner).records == []


def test_delete_stamps_the_attempt_and_the_upload_with_one_instant(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    result = service.delete(owner, str(attempt.attempt_id))
    assert _attempt_row(sessionmaker_, attempt.attempt_id).deleted_at == result.deleted_at
    assert _upload_row(sessionmaker_, attempt.upload_id).deleted_at == result.deleted_at


def test_delete_nulls_the_idempotency_key(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """Otherwise a re-upload of the same scan collides with the hidden row."""
    assert _upload_row(sessionmaker_, attempt.upload_id).idempotency_key is not None
    service.delete(owner, str(attempt.attempt_id))
    assert _upload_row(sessionmaker_, attempt.upload_id).idempotency_key is None


def test_delete_returns_what_the_undo_toast_needs(
    service: PaperDeletionService, owner: str, attempt: Seeded
) -> None:
    result = service.delete(owner, str(attempt.attempt_id))
    assert isinstance(result, DeletedPaper)
    assert result.attempt_id == attempt.attempt_id
    assert result.subject_code == "0625"
    assert result.paper_label == "0625 Paper 4, May/June 2024"
    assert result.restore_deadline == restore_deadline(result.deleted_at)
    assert result.sibling_attempt_ids == [attempt.attempt_id]
    assert result.withdrawn_item_ids == []


def test_delete_withdraws_open_review_items_at_the_same_instant(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
    open_item: uuid.UUID,
) -> None:
    result = service.delete(owner, str(attempt.attempt_id))
    item = _item_row(sessionmaker_, open_item)
    assert item.status is ReviewStatus.withdrawn
    assert item.withdrawn_at == result.deleted_at
    assert item.resolved_by is None  # a student's delete is not a teacher's judgement
    assert result.withdrawn_item_ids == [open_item]


def test_delete_leaves_a_closed_review_item_alone(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """Only open items are withdrawn; a teacher's past verdict is history."""
    resolved = _seed_item(
        sessionmaker_, attempt.attempt_id, ReviewReason.low_confidence, ReviewStatus.resolved
    )
    result = service.delete(owner, str(attempt.attempt_id))
    item = _item_row(sessionmaker_, resolved)
    assert item.status is ReviewStatus.resolved
    assert item.withdrawn_at is None
    assert result.withdrawn_item_ids == []


# ── R7: the unit of deletion is the upload ──────────────────────────────────


def test_deleting_one_attempt_deletes_every_attempt_on_its_upload(
    service: PaperDeletionService,
    store: DbHistoryStore,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """A re-mark mints a second attempt on the same scan; both must go."""
    sibling = _seed_attempt(sessionmaker_, owner, attempt.upload_id)
    sibling_item = _seed_item(sessionmaker_, sibling.attempt_id, ReviewReason.low_confidence)
    assert {r.attempt_id for r in store.load(owner).records} == {
        str(attempt.attempt_id),
        str(sibling.attempt_id),
    }

    result = service.delete(owner, str(attempt.attempt_id))

    assert store.load(owner).records == []
    assert _attempt_row(sessionmaker_, sibling.attempt_id).deleted_at == result.deleted_at
    assert result.sibling_attempt_ids == sorted([attempt.attempt_id, sibling.attempt_id])
    assert result.withdrawn_item_ids == [sibling_item]
    assert _item_row(sessionmaker_, sibling_item).withdrawn_at == result.deleted_at


def test_an_integrity_hold_on_a_sibling_refuses_the_whole_upload(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """Deleting the clean attempt must not take a held sibling's scan with it."""
    sibling = _seed_attempt(sessionmaker_, owner, attempt.upload_id)
    _seed_question(sessionmaker_, sibling.attempt_id, ai_detection=True)

    with pytest.raises(PaperNotDeletableError) as exc:
        service.delete(owner, str(attempt.attempt_id))

    assert str(exc.value) == _HOLD_REFUSAL
    assert exc.value.deletable_from == integrity_hold_until(sibling.recorded_at)
    _assert_untouched(sessionmaker_, attempt)
    assert _attempt_row(sessionmaker_, sibling.attempt_id).deleted_at is None


# ── ownership and not-found ─────────────────────────────────────────────────


def test_another_students_paper_is_a_404_not_a_403(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    stranger: str,
    attempt: Seeded,
) -> None:
    with pytest.raises(PaperNotFoundError):
        service.delete(stranger, str(attempt.attempt_id))
    _assert_untouched(sessionmaker_, attempt)


def test_deleting_twice_is_a_404(
    service: PaperDeletionService, owner: str, attempt: Seeded
) -> None:
    service.delete(owner, str(attempt.attempt_id))
    with pytest.raises(PaperNotFoundError):
        service.delete(owner, str(attempt.attempt_id))


@pytest.mark.parametrize("bad_id", ["not-a-uuid", ""])
def test_a_malformed_attempt_id_is_a_404(
    service: PaperDeletionService, owner: str, bad_id: str
) -> None:
    with pytest.raises(PaperNotFoundError):
        service.delete(owner, bad_id)


def test_an_unknown_attempt_id_is_a_404(service: PaperDeletionService, owner: str) -> None:
    with pytest.raises(PaperNotFoundError):
        service.delete(owner, str(uuid.uuid4()))


def test_a_quiz_attempt_is_refused(
    service: PaperDeletionService, sessionmaker_: sessionmaker[Session], owner: str
) -> None:
    quiz = _seed_attempt(sessionmaker_, owner, None, origin=AttemptOrigin.quiz)
    with pytest.raises(PaperNotDeletableError) as exc:
        service.delete(owner, str(quiz.attempt_id))
    assert exc.value.deletable_from is None
    assert _attempt_row(sessionmaker_, quiz.attempt_id).deleted_at is None


# ── D8: the integrity hold ──────────────────────────────────────────────────


def test_an_integrity_flagged_paper_is_refused_with_a_date(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    flagged_attempt: Seeded,
) -> None:
    with pytest.raises(PaperNotDeletableError) as exc:
        service.delete(owner, str(flagged_attempt.attempt_id))
    assert exc.value.deletable_from == integrity_hold_until(flagged_attempt.recorded_at)
    _assert_untouched(sessionmaker_, flagged_attempt)


def test_the_hold_refusal_never_names_its_reason(
    service: PaperDeletionService, owner: str, flagged_attempt: Seeded
) -> None:
    """QUALITY-BAR.md: integrity is teacher-only. The copy is generic, exactly."""
    with pytest.raises(PaperNotDeletableError) as exc:
        service.delete(owner, str(flagged_attempt.attempt_id))
    assert str(exc.value) == _HOLD_REFUSAL
    assert exc.value.args == (_HOLD_REFUSAL,)


def test_an_integrity_flag_past_the_retention_window_does_not_block(
    service: PaperDeletionService, sessionmaker_: sessionmaker[Session], owner: str
) -> None:
    old = _seed_attempt(
        sessionmaker_,
        owner,
        _seed_upload(sessionmaker_, owner),
        recorded_at=datetime.now(UTC) - timedelta(days=RETENTION_DAYS + 1),
    )
    _seed_question(sessionmaker_, old.attempt_id, plagiarism=True)
    service.delete(owner, str(old.attempt_id))  # does not raise


def test_a_low_confidence_review_does_not_block_deletion(
    service: PaperDeletionService, owner: str, attempt: Seeded, open_item: uuid.UUID
) -> None:
    """The predicate is the integrity flag, not 'has a review item'."""
    service.delete(owner, str(attempt.attempt_id))  # does not raise


@pytest.mark.parametrize("closed_as", [ReviewStatus.resolved, ReviewStatus.dismissed])
def test_a_teacher_closing_the_integrity_item_lifts_the_block(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    flagged_attempt: Seeded,
    integrity_item: uuid.UUID,
    closed_as: ReviewStatus,
) -> None:
    """R4: both outcomes mean a teacher looked. The student is never told which."""
    _set_status(sessionmaker_, integrity_item, closed_as)
    service.delete(owner, str(flagged_attempt.attempt_id))  # does not raise


def test_an_open_integrity_item_keeps_the_block(
    service: PaperDeletionService, owner: str, flagged_attempt: Seeded, integrity_item: uuid.UUID
) -> None:
    with pytest.raises(PaperNotDeletableError):
        service.delete(owner, str(flagged_attempt.attempt_id))


def test_a_flag_with_no_integrity_item_keeps_the_block(
    service: PaperDeletionService, owner: str, flagged_attempt: Seeded
) -> None:
    """The lift needs at least one closed item; an empty set clears nothing."""
    with pytest.raises(PaperNotDeletableError):
        service.delete(owner, str(flagged_attempt.attempt_id))


def test_a_withdrawn_integrity_item_does_not_lift_the_block(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    flagged_attempt: Seeded,
    integrity_item: uuid.UUID,
) -> None:
    """R4a. Without this, delete+restore lifts a student's own hold.

    The cycle is the attack: deleting withdraws the item, and if `withdrawn`
    counted as closed, the restored paper would be freely deletable. Restore
    reopens the item (Task 6), so the block only holds if `withdrawn` is
    absent from the lifting set here.
    """
    _set_status(sessionmaker_, integrity_item, ReviewStatus.withdrawn)
    with pytest.raises(PaperNotDeletableError):
        service.delete(owner, str(flagged_attempt.attempt_id))


def test_one_resolved_and_one_open_integrity_item_keeps_the_block(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    flagged_attempt: Seeded,
    integrity_item: uuid.UUID,
) -> None:
    """§13: closing the plagiarism item does not clear an open AI-detection one."""
    _seed_item(sessionmaker_, flagged_attempt.attempt_id, ReviewReason.ai_detection_flag)
    _set_status(sessionmaker_, integrity_item, ReviewStatus.resolved)
    with pytest.raises(PaperNotDeletableError):
        service.delete(owner, str(flagged_attempt.attempt_id))
    _assert_untouched(sessionmaker_, flagged_attempt)


def test_a_closed_low_confidence_item_does_not_lift_an_integrity_hold(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    flagged_attempt: Seeded,
    integrity_item: uuid.UUID,
) -> None:
    """The lifting query must filter on reason, not merely on status."""
    _seed_item(
        sessionmaker_,
        flagged_attempt.attempt_id,
        ReviewReason.low_confidence,
        ReviewStatus.resolved,
    )
    with pytest.raises(PaperNotDeletableError):
        service.delete(owner, str(flagged_attempt.attempt_id))


def test_a_closed_low_confidence_item_alone_does_not_lift_an_integrity_hold(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    flagged_attempt: Seeded,
) -> None:
    """With no integrity item at all, a closed marking review must not count."""
    _seed_item(
        sessionmaker_,
        flagged_attempt.attempt_id,
        ReviewReason.low_confidence,
        ReviewStatus.resolved,
    )
    with pytest.raises(PaperNotDeletableError):
        service.delete(owner, str(flagged_attempt.attempt_id))


def test_a_teacher_override_does_not_block_deletion(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    teacher = uuid.UUID(_seed_user(sessionmaker_))
    _seed_question(sessionmaker_, attempt.attempt_id, overridden_by=teacher)
    service.delete(owner, str(attempt.attempt_id))  # D10: does not raise


# ── T5 review hardening ─────────────────────────────────────────────────────


def test_a_sibling_owned_by_someone_else_refuses_the_delete(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    stranger: str,
    attempt: Seeded,
) -> None:
    """No constraint ties attempts.user_id to uploads.user_id; the service does."""
    foreign = _seed_attempt(sessionmaker_, stranger, attempt.upload_id)
    with pytest.raises(PaperNotFoundError):
        service.delete(owner, str(attempt.attempt_id))
    _assert_untouched(sessionmaker_, attempt)
    assert _attempt_row(sessionmaker_, foreign.attempt_id).deleted_at is None


def test_an_upload_already_deleted_keeps_its_instant_and_key(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """Restore matches siblings on ``deleted_at``; re-stamping would strand them."""
    earlier = datetime.now(UTC) - timedelta(days=1)
    with sessionmaker_.begin() as session:
        upload = _upload_row(sessionmaker_, attempt.upload_id)
        session.add(upload)
        upload.deleted_at = earlier
        upload.idempotency_key = "kept"

    result = service.delete(owner, str(attempt.attempt_id))

    after = _upload_row(sessionmaker_, attempt.upload_id)
    assert result.deleted_at != earlier
    assert after.deleted_at == earlier
    assert after.idempotency_key == "kept"


def test_two_held_siblings_are_deletable_from_the_later_hold_end(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """The whole upload is deletable only once every hold has ended."""
    now = datetime.now(UTC)
    older = _seed_attempt(
        sessionmaker_, owner, attempt.upload_id, recorded_at=now - timedelta(days=10)
    )
    newer = _seed_attempt(
        sessionmaker_, owner, attempt.upload_id, recorded_at=now - timedelta(days=2)
    )
    _seed_question(sessionmaker_, older.attempt_id, plagiarism=True)
    _seed_question(sessionmaker_, newer.attempt_id, ai_detection=True)

    with pytest.raises(PaperNotDeletableError) as exc:
        service.delete(owner, str(attempt.attempt_id))

    assert exc.value.deletable_from == integrity_hold_until(newer.recorded_at)
    assert exc.value.deletable_from != integrity_hold_until(older.recorded_at)
    _assert_untouched(sessionmaker_, attempt)


def test_a_non_past_paper_sibling_on_the_upload_refuses_the_delete(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    quiz = _seed_attempt(sessionmaker_, owner, attempt.upload_id, origin=AttemptOrigin.quiz)
    with pytest.raises(PaperNotDeletableError) as exc:
        service.delete(owner, str(attempt.attempt_id))
    assert exc.value.deletable_from is None
    _assert_untouched(sessionmaker_, attempt)
    assert _attempt_row(sessionmaker_, quiz.attempt_id).deleted_at is None


@pytest.mark.parametrize(
    ("subject_code", "paper_number", "session_month", "session_year", "expected"),
    [
        ("0625", 4, SessionMonth.may_june, 2024, "0625 Paper 4, May/June 2024"),
        (None, 4, SessionMonth.may_june, 2024, "Paper 4, May/June 2024"),
        ("0625", None, SessionMonth.may_june, 2024, "0625, May/June 2024"),
        (None, None, SessionMonth.may_june, 2024, "Past paper, May/June 2024"),
        ("0625", 4, SessionMonth.may_june, None, "0625 Paper 4, May/June"),
        ("0625", 4, None, 2024, "0625 Paper 4, 2024"),
        ("0625", 4, None, None, "0625 Paper 4"),
        (None, None, None, None, "Past paper"),
    ],
)
def test_paper_label_degrades_without_doubling_words(
    subject_code: str | None,
    paper_number: int | None,
    session_month: SessionMonth | None,
    session_year: int | None,
    expected: str,
) -> None:
    """Task 9 interpolates this into teacher notifications, so it must read well."""
    attempt = Attempt(
        subject_code=subject_code,
        paper_number=paper_number,
        session_month=session_month,
        session_year=session_year,
    )
    assert paper_label(attempt) == expected


# ── restore (Task 6) ────────────────────────────────────────────────────────


def _backdate_deletion(sm: sessionmaker[Session], upload_id: uuid.UUID | None, days: int) -> None:
    """Move one deletion ``days`` into the past, keeping its instants equal.

    Restore matches the attempts and items on equality with the upload's
    ``deleted_at``, so all three are shifted together.
    """
    shift = timedelta(days=days)
    with sm.begin() as session:
        upload = session.scalars(
            select(Upload)
            .where(Upload.id == upload_id)
            .execution_options(**{INCLUDE_DELETED: True})
        ).one()
        instant = upload.deleted_at
        assert instant is not None
        session.execute(
            sa.update(Attempt)
            .where(Attempt.upload_id == upload_id, Attempt.deleted_at == instant)
            .values(deleted_at=instant - shift)
        )
        session.execute(
            sa.update(ReviewQueueItem)
            .where(ReviewQueueItem.withdrawn_at == instant)
            .values(withdrawn_at=instant - shift)
        )
        upload.deleted_at = instant - shift


def _set_upload_status(
    sm: sessionmaker[Session], upload_id: uuid.UUID | None, status: UploadStatus
) -> None:
    with sm.begin() as session:
        session.execute(sa.update(Upload).where(Upload.id == upload_id).values(status=status))


def _stamp_attempt(sm: sessionmaker[Session], attempt_id: uuid.UUID, when: datetime | None) -> None:
    with sm.begin() as session:
        session.execute(sa.update(Attempt).where(Attempt.id == attempt_id).values(deleted_at=when))


@pytest.fixture
def previously_dismissed_item(sessionmaker_: sessionmaker[Session], attempt: Seeded) -> uuid.UUID:
    """A review a teacher closed before the delete: not the delete's to reopen."""
    return _seed_item(
        sessionmaker_, attempt.attempt_id, ReviewReason.low_confidence, ReviewStatus.dismissed
    )


def test_restore_brings_the_paper_back(
    service: PaperDeletionService, store: DbHistoryStore, owner: str, attempt: Seeded
) -> None:
    service.delete(owner, str(attempt.attempt_id))
    assert store.load(owner).records == []
    service.restore(owner, str(attempt.attempt_id))
    assert [r.attempt_id for r in store.load(owner).records] == [str(attempt.attempt_id)]


def test_restore_clears_the_upload_stamp_but_not_the_released_key(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """The key was released for a re-upload and may belong to another row now."""
    service.delete(owner, str(attempt.attempt_id))
    service.restore(owner, str(attempt.attempt_id))
    upload = _upload_row(sessionmaker_, attempt.upload_id)
    assert upload.deleted_at is None
    assert upload.idempotency_key is None
    assert _attempt_row(sessionmaker_, attempt.attempt_id).deleted_at is None


def test_restore_reopens_exactly_the_items_this_deletion_withdrew(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
    open_item: uuid.UUID,
    previously_dismissed_item: uuid.UUID,
) -> None:
    """Delete then restore must not launder a review item out of the queue."""
    original_created_at = _item_row(sessionmaker_, open_item).created_at
    service.delete(owner, str(attempt.attempt_id))
    assert _item_row(sessionmaker_, open_item).status is ReviewStatus.withdrawn

    service.restore(owner, str(attempt.attempt_id))

    reopened = _item_row(sessionmaker_, open_item)
    untouched = _item_row(sessionmaker_, previously_dismissed_item)
    assert reopened.status is ReviewStatus.open
    assert reopened.withdrawn_at is None
    assert reopened.created_at == original_created_at  # sorts where it always did
    assert untouched.status is ReviewStatus.dismissed  # not swept up


def test_restore_leaves_an_item_withdrawn_at_another_instant_alone(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
    open_item: uuid.UUID,
) -> None:
    """The match is equality with this deletion's instant, not 'any withdrawn item'."""
    stray = _seed_item(
        sessionmaker_, attempt.attempt_id, ReviewReason.low_confidence, ReviewStatus.withdrawn
    )
    with sessionmaker_.begin() as session:
        session.execute(
            sa.update(ReviewQueueItem)
            .where(ReviewQueueItem.id == stray)
            .values(withdrawn_at=datetime.now(UTC) - timedelta(days=3))
        )
    service.delete(owner, str(attempt.attempt_id))
    service.restore(owner, str(attempt.attempt_id))
    assert _item_row(sessionmaker_, open_item).status is ReviewStatus.open
    assert _item_row(sessionmaker_, stray).status is ReviewStatus.withdrawn


def test_restore_after_the_window_is_refused(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
    open_item: uuid.UUID,
) -> None:
    service.delete(owner, str(attempt.attempt_id))
    _backdate_deletion(sessionmaker_, attempt.upload_id, days=RETENTION_DAYS + 1)
    with pytest.raises(PaperNotRestorableError):
        service.restore(owner, str(attempt.attempt_id))
    assert _attempt_row(sessionmaker_, attempt.attempt_id).deleted_at is not None
    assert _upload_row(sessionmaker_, attempt.upload_id).deleted_at is not None
    assert _item_row(sessionmaker_, open_item).status is ReviewStatus.withdrawn


def test_restore_just_inside_the_window_succeeds(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
    open_item: uuid.UUID,
) -> None:
    """The backdate keeps the instants equal, so only the window can refuse."""
    service.delete(owner, str(attempt.attempt_id))
    _backdate_deletion(sessionmaker_, attempt.upload_id, days=RETENTION_DAYS - 1)
    service.restore(owner, str(attempt.attempt_id))
    assert _attempt_row(sessionmaker_, attempt.attempt_id).deleted_at is None
    assert _item_row(sessionmaker_, open_item).status is ReviewStatus.open


def test_restoring_a_live_paper_is_a_404(
    service: PaperDeletionService, owner: str, attempt: Seeded
) -> None:
    with pytest.raises(PaperNotFoundError):
        service.restore(owner, str(attempt.attempt_id))


def test_another_student_cannot_restore(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    stranger: str,
    attempt: Seeded,
) -> None:
    service.delete(owner, str(attempt.attempt_id))
    with pytest.raises(PaperNotFoundError):
        service.restore(stranger, str(attempt.attempt_id))
    assert _attempt_row(sessionmaker_, attempt.attempt_id).deleted_at is not None


@pytest.mark.parametrize("bad_id", ["not-a-uuid", ""])
def test_restoring_a_malformed_id_is_a_404(
    service: PaperDeletionService, owner: str, bad_id: str
) -> None:
    with pytest.raises(PaperNotFoundError):
        service.restore(owner, bad_id)


def test_restoring_an_unknown_id_is_a_404(service: PaperDeletionService, owner: str) -> None:
    with pytest.raises(PaperNotFoundError):
        service.restore(owner, str(uuid.uuid4()))


def test_restoring_twice_is_a_404(
    service: PaperDeletionService, owner: str, attempt: Seeded
) -> None:
    service.delete(owner, str(attempt.attempt_id))
    service.restore(owner, str(attempt.attempt_id))
    with pytest.raises(PaperNotFoundError):
        service.restore(owner, str(attempt.attempt_id))


# ── R7: restore covers the whole upload ─────────────────────────────────────


def test_restoring_one_attempt_restores_the_whole_upload(
    service: PaperDeletionService,
    store: DbHistoryStore,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """The unit of restore is the upload, as it is for delete."""
    sibling = _seed_attempt(sessionmaker_, owner, attempt.upload_id)
    sibling_item = _seed_item(sessionmaker_, sibling.attempt_id, ReviewReason.low_confidence)
    service.delete(owner, str(sibling.attempt_id))

    service.restore(owner, str(attempt.attempt_id))

    assert {r.attempt_id for r in store.load(owner).records} == {
        str(attempt.attempt_id),
        str(sibling.attempt_id),
    }
    assert _item_row(sessionmaker_, sibling_item).status is ReviewStatus.open


def test_restore_does_not_revive_an_attempt_deleted_at_another_instant(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """Only the attempts stamped with the upload's own instant come back."""
    earlier = _seed_attempt(sessionmaker_, owner, attempt.upload_id)
    _stamp_attempt(sessionmaker_, earlier.attempt_id, datetime.now(UTC) - timedelta(days=2))
    service.delete(owner, str(attempt.attempt_id))

    service.restore(owner, str(attempt.attempt_id))

    assert _attempt_row(sessionmaker_, attempt.attempt_id).deleted_at is None
    assert _attempt_row(sessionmaker_, earlier.attempt_id).deleted_at is not None


def test_restoring_an_attempt_not_deleted_with_its_upload_is_refused(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """Undoing the upload's deletion would not bring this attempt back, so refuse."""
    earlier = _seed_attempt(sessionmaker_, owner, attempt.upload_id)
    _stamp_attempt(sessionmaker_, earlier.attempt_id, datetime.now(UTC) - timedelta(days=2))
    service.delete(owner, str(attempt.attempt_id))

    with pytest.raises(PaperNotRestorableError):
        service.restore(owner, str(earlier.attempt_id))
    assert _attempt_row(sessionmaker_, attempt.attempt_id).deleted_at is not None
    assert _upload_row(sessionmaker_, attempt.upload_id).deleted_at is not None


def test_a_deleted_sibling_owned_by_someone_else_refuses_the_restore(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    stranger: str,
    attempt: Seeded,
) -> None:
    """Mirror of delete's check: restore never revives another student's attempt."""
    service.delete(owner, str(attempt.attempt_id))
    foreign = _seed_attempt(sessionmaker_, stranger, attempt.upload_id)
    _stamp_attempt(
        sessionmaker_, foreign.attempt_id, _upload_row(sessionmaker_, attempt.upload_id).deleted_at
    )

    with pytest.raises(PaperNotFoundError):
        service.restore(owner, str(attempt.attempt_id))
    assert _attempt_row(sessionmaker_, attempt.attempt_id).deleted_at is not None
    assert _attempt_row(sessionmaker_, foreign.attempt_id).deleted_at is not None


# ── the laundering cycle (I5, moved here from Task 5) ───────────────────────


def test_a_flag_raised_while_deleted_holds_after_restore(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """A flag and its review that land on a deleted paper still bind it once restored."""
    service.delete(owner, str(attempt.attempt_id))
    _seed_question(sessionmaker_, attempt.attempt_id, plagiarism=True)
    _seed_item(sessionmaker_, attempt.attempt_id, ReviewReason.plagiarism_flag)

    service.restore(owner, str(attempt.attempt_id))

    with pytest.raises(PaperNotDeletableError) as exc:
        service.delete(owner, str(attempt.attempt_id))
    assert str(exc.value) == _HOLD_REFUSAL
    assert _attempt_row(sessionmaker_, attempt.attempt_id).deleted_at is None


def test_delete_then_restore_puts_an_integrity_review_back_in_the_queue(
    service: PaperDeletionService, sessionmaker_: sessionmaker[Session], owner: str
) -> None:
    """Past the hold the flagged paper may go, but restoring it restores its review."""
    old = _seed_attempt(
        sessionmaker_,
        owner,
        _seed_upload(sessionmaker_, owner),
        recorded_at=datetime.now(UTC) - timedelta(days=RETENTION_DAYS + 1),
    )
    _seed_question(sessionmaker_, old.attempt_id, plagiarism=True)
    item_id = _seed_item(sessionmaker_, old.attempt_id, ReviewReason.plagiarism_flag)
    original_created_at = _item_row(sessionmaker_, item_id).created_at

    service.delete(owner, str(old.attempt_id))
    assert _item_row(sessionmaker_, item_id).status is ReviewStatus.withdrawn
    service.restore(owner, str(old.attempt_id))

    item = _item_row(sessionmaker_, item_id)
    assert item.status is ReviewStatus.open
    assert item.withdrawn_at is None
    assert item.created_at == original_created_at


# ── stale ``processing`` (Task 5a controller addition 3) ────────────────────


def test_delete_ends_a_processing_upload_as_complete(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
) -> None:
    """Deleted mid-run, nothing else writes a terminal status; a restore would show a ghost run."""
    _set_upload_status(sessionmaker_, attempt.upload_id, UploadStatus.processing)
    service.delete(owner, str(attempt.attempt_id))
    assert _upload_row(sessionmaker_, attempt.upload_id).status is UploadStatus.complete


@pytest.mark.parametrize("status", [UploadStatus.complete, UploadStatus.failed])
def test_delete_leaves_a_terminal_upload_status_alone(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
    status: UploadStatus,
) -> None:
    _set_upload_status(sessionmaker_, attempt.upload_id, status)
    service.delete(owner, str(attempt.attempt_id))
    assert _upload_row(sessionmaker_, attempt.upload_id).status is status


# ── concurrency ─────────────────────────────────────────────────────────────


def _lock_and_write_order(sm: sessionmaker[Session], run: Callable[[], object]) -> list[str]:
    """The tables ``run`` locks or writes, in statement order: ``"lock uploads"`` etc."""
    engine = sm.kw["bind"]
    seen: list[str] = []

    def record(
        conn: object, cursor: object, statement: str, *args: object, **kwargs: object
    ) -> None:
        sql = " ".join(statement.split())
        if sql.endswith("FOR UPDATE"):
            seen.append("lock " + sql.split(" FROM ", 1)[1].split(" ", 1)[0])
        elif sql.startswith("UPDATE "):
            seen.append("update " + sql.split(" ", 2)[1])

    sa.event.listen(engine, "before_cursor_execute", record)
    try:
        run()
    finally:
        sa.event.remove(engine, "before_cursor_execute", record)
    return seen


def test_restore_locks_in_deletes_order(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
    open_item: uuid.UUID,
) -> None:
    """Upload, then attempts, then review items — the order delete and persist take.

    A restore that locked the attempts before the upload could hold them while
    a delete, already holding the upload, waits on them: a lock cycle.
    """
    deleted = _lock_and_write_order(
        sessionmaker_, lambda: service.delete(owner, str(attempt.attempt_id))
    )
    restored = _lock_and_write_order(
        sessionmaker_, lambda: service.restore(owner, str(attempt.attempt_id))
    )
    expected = ["lock uploads", "lock attempts", "update review_queue"]
    assert [step for step in deleted if step in expected] == expected, deleted
    assert [step for step in restored if step in expected] == expected, restored


def test_a_second_restore_queued_behind_the_first_is_a_404(
    service: PaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    owner: str,
    attempt: Seeded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A double-clicked Undo: the second restore waits on the upload, then finds it live.

    Its unlocked read saw the paper deleted, so only the re-check on the locked
    copy stops it, and that copy must be the committed row, not the stale one.
    """
    service.delete(owner, str(attempt.attempt_id))

    inside, release = threading.Event(), threading.Event()
    real = PaperDeletionService._lock_siblings
    calls = 0

    def paused(
        self: PaperDeletionService, session: Session, upload_id: uuid.UUID
    ) -> Sequence[Attempt]:
        nonlocal calls
        calls += 1
        siblings = real(self, session, upload_id)
        if calls == 1:
            inside.set()
            assert release.wait(timeout=20)
        return siblings

    monkeypatch.setattr(PaperDeletionService, "_lock_siblings", paused)
    first = _Paused(lambda: service.restore(owner, str(attempt.attempt_id)))
    assert inside.wait(timeout=20)
    second = _Paused(lambda: service.restore(owner, str(attempt.attempt_id)))
    _wait_until_a_backend_waits_on_a_lock(sessionmaker_)
    release.set()
    first.join()
    second.join()

    assert first.error is None
    assert isinstance(second.error, PaperNotFoundError)
    assert calls == 2
    assert _attempt_row(sessionmaker_, attempt.attempt_id).deleted_at is None
