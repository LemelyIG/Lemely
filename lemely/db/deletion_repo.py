"""A student's paper deletion (design ``2026-09-22-paper-deletion-design.md``).

Deletion is a soft delete: ``deleted_at`` is stamped and the loader criterion in
:mod:`lemely.db.session` hides the row from every ordinary reader. This module
is one of the few permitted callers of :data:`~lemely.db.session.INCLUDE_DELETED`,
because it must see a row in order to decide it is already gone.

**The unit of deletion is the upload (R7, §13).** Re-running marking on one scan
mints a new attempt each time, so one upload can back several attempts. Deleting
any of them deletes all of them and the upload together, at one instant; a
refusal on any of them refuses the whole delete.

**The integrity hold (D8, §8) never names itself.** A paper with an integrity
flag inside the retention window is refused with generic copy and a date. The
flags are teacher-only (``BUILD/QUALITY-BAR.md``): no message, attribute or
exception raised here says *why*.

Two hazards of the loader criterion shape the reads below. ``session.get``
answers from the identity map with no SQL, and relationship lazy loads carry no
criterion for a parent loaded with ``include_deleted``. So every read is an
explicit ``select`` — sibling attempts and review items are never reached by
walking ``upload.attempts`` or any other relationship attribute.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import select

from lemely.core.deletion import integrity_hold_until, restore_deadline
from lemely.db.models.attempts import Attempt, QuestionResult, Upload
from lemely.db.models.enums import (
    SESSION_MONTH_LABELS,
    AttemptOrigin,
    ReviewReason,
    ReviewStatus,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.session import INCLUDE_DELETED

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session, sessionmaker

#: The outcomes that mean a teacher looked at an integrity finding (R4).
#: ``withdrawn`` is deliberately absent (R4a): it is set by a student's own
#: deletion, so counting it would let a delete-then-restore cycle lift the
#: student's own hold. Adding a member to this set is a security decision.
_TEACHER_CLOSED = (ReviewStatus.resolved, ReviewStatus.dismissed)

_INTEGRITY_REASONS = (ReviewReason.plagiarism_flag, ReviewReason.ai_detection_flag)

#: The refusal copy for a held paper. Generic by design (D8): it must read the
#: same whatever the reason, so it names neither integrity nor review.
_HOLD_MESSAGE = "This paper can't be deleted yet."

_NOT_UPLOADED_MESSAGE = "Only uploaded papers can be deleted."


class PaperDeletionError(Exception):
    """Base class for paper deletion and restore failures."""


class PaperNotFoundError(PaperDeletionError):
    """No live paper with this id belongs to the caller (→ 404).

    Deliberately also raised for another student's paper: a 403 there would
    confirm the id exists.
    """


class PaperNotDeletableError(PaperDeletionError):
    """The paper exists and is the caller's, but may not be deleted now (→ 409).

    ``deletable_from`` is the instant an integrity hold ends, or ``None`` when
    the paper can never be deleted (a quiz attempt). It is a statement about
    now, not a promise: a teacher closing the review can lift the hold earlier.
    """

    def __init__(self, message: str, *, deletable_from: datetime | None) -> None:
        super().__init__(message)
        self.deletable_from = deletable_from


class PaperNotRestorableError(PaperDeletionError):
    """The paper was deleted but can no longer be restored (used by restore)."""


@dataclass(frozen=True, slots=True)
class DeletedPaper:
    """The outcome of one deletion: what the undo toast and notifications need."""

    attempt_id: uuid.UUID
    subject_code: str | None
    paper_label: str
    deleted_at: datetime
    restore_deadline: datetime
    withdrawn_item_ids: list[uuid.UUID]
    """Every review item this deletion withdrew, across all sibling attempts."""
    sibling_attempt_ids: list[uuid.UUID]
    """Every attempt this deletion stamped, the addressed one included, by id."""


def paper_label(attempt: Attempt) -> str:
    """A human name for the paper, e.g. ``"0625 Paper 4, May/June 2024"``.

    Uses :data:`SESSION_MONTH_LABELS`, the same lookup ``attempt_to_record``
    uses for ``ExamMetadata``, so the paper reads the same here as in history.
    """
    name = " ".join(
        part
        for part in (
            attempt.subject_code or "Past paper",
            f"Paper {attempt.paper_number}" if attempt.paper_number is not None else None,
        )
        if part
    )
    if attempt.session_month is None:
        return name
    session = SESSION_MONTH_LABELS[attempt.session_month]
    if attempt.session_year is not None:
        session = f"{session} {attempt.session_year}"
    return f"{name}, {session}"


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


class PaperDeletionService:
    """Soft-deletes a student's own uploaded paper, in one transaction."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def delete(self, user_id: str, attempt_id: str) -> DeletedPaper:
        """Delete the paper ``attempt_id`` and every attempt sharing its upload.

        Stamps ``deleted_at`` on each sibling attempt and on the upload with one
        instant, nulls the upload's ``idempotency_key``, and withdraws every
        open review item on the siblings with ``withdrawn_at`` equal to that
        instant — the equality restore selects on. Notifying teachers happens
        after commit, in the caller.

        Raises:
            PaperNotFoundError: no live attempt with this id belongs to
                ``user_id`` (including a malformed id, or another student's).
            PaperNotDeletableError: a sibling is not an uploaded past paper
                (``deletable_from=None``), or a sibling is under the integrity
                hold (``deletable_from`` = the latest hold end among them).
        """
        owner = _parse_uuid(user_id)
        parsed_id = _parse_uuid(attempt_id)
        if owner is None or parsed_id is None:
            raise PaperNotFoundError("No such paper")
        now = datetime.now(UTC)

        with self._sessionmaker.begin() as session:
            # An unlocked read first, only to learn the upload: locking the
            # addressed row before its siblings would break id-order locking.
            addressed = session.scalars(
                select(Attempt)
                .where(Attempt.id == parsed_id)
                .execution_options(**{INCLUDE_DELETED: True})
            ).one_or_none()
            if addressed is None or addressed.user_id != owner:
                raise PaperNotFoundError("No such paper")
            if addressed.upload_id is None:
                if addressed.deleted_at is not None:
                    raise PaperNotFoundError("No such paper")
                raise PaperNotDeletableError(_NOT_UPLOADED_MESSAGE, deletable_from=None)
            upload_id = addressed.upload_id

            siblings = self._lock_siblings(session, upload_id)
            addressed = next((a for a in siblings if a.id == parsed_id), None)
            if addressed is None or addressed.user_id != owner or addressed.deleted_at is not None:
                raise PaperNotFoundError("No such paper")
            live = [a for a in siblings if a.deleted_at is None]

            if any(a.origin is not AttemptOrigin.past_paper for a in live):
                raise PaperNotDeletableError(_NOT_UPLOADED_MESSAGE, deletable_from=None)
            holds = [
                hold for a in live if (hold := self._integrity_hold(session, a, now)) is not None
            ]
            if holds:
                raise PaperNotDeletableError(_HOLD_MESSAGE, deletable_from=max(holds))

            for sibling in live:
                sibling.deleted_at = now
            upload = session.scalars(
                select(Upload)
                .where(Upload.id == upload_id)
                .with_for_update()
                .execution_options(**{INCLUDE_DELETED: True}, populate_existing=True)
            ).one()
            upload.deleted_at = now
            # ux_uploads_user_idempotency survives the soft delete, so a re-upload
            # of the same scan would collide with a row the student cannot see.
            upload.idempotency_key = None

            sibling_ids = [a.id for a in live]
            withdrawn = self._withdraw_open_items(session, sibling_ids, now)

            return DeletedPaper(
                attempt_id=addressed.id,
                subject_code=addressed.subject_code,
                paper_label=paper_label(addressed),
                deleted_at=now,
                restore_deadline=restore_deadline(now),
                withdrawn_item_ids=withdrawn,
                sibling_attempt_ids=sibling_ids,
            )

    def _lock_siblings(self, session: Session, upload_id: uuid.UUID) -> Sequence[Attempt]:
        """Lock every attempt on ``upload_id`` in id order, deleted ones included.

        ``populate_existing`` overwrites the identity-map copy from the unlocked
        read, so ``deleted_at`` is the value read under the lock.
        """
        return session.scalars(
            select(Attempt)
            .where(Attempt.upload_id == upload_id)
            .order_by(Attempt.id)
            .with_for_update()
            .execution_options(**{INCLUDE_DELETED: True}, populate_existing=True)
        ).all()

    def _integrity_hold(self, session: Session, attempt: Attempt, now: datetime) -> datetime | None:
        """The instant this attempt's D8 hold ends, or ``None`` if it is not held.

        Held when all three stand: an integrity flag on a question, ``now``
        inside the retention window from ``recorded_at``, and no teacher
        clearance of its integrity review items.
        """
        hold_until = integrity_hold_until(attempt.recorded_at)
        if now >= hold_until:
            return None
        if not self._has_integrity_flag(session, attempt.id):
            return None
        if self._integrity_items_closed_by_teacher(session, attempt.id):
            return None
        return hold_until

    def _has_integrity_flag(self, session: Session, attempt_id: uuid.UUID) -> bool:
        """Whether any question on this attempt carries an integrity finding (D8).

        Reads the two booleans, never ``review_reason`` text and never the review
        queue: those are echoes of this fact, and an echo can be resolved away
        while the fact stands.
        """
        return bool(
            session.scalar(
                select(
                    select(QuestionResult.id)
                    .where(
                        QuestionResult.attempt_id == attempt_id,
                        sa.or_(
                            QuestionResult.plagiarism_flagged.is_(True),
                            QuestionResult.ai_detection_flagged.is_(True),
                        ),
                    )
                    .exists()
                )
            )
        )

    def _integrity_items_closed_by_teacher(self, session: Session, attempt_id: uuid.UUID) -> bool:
        """Whether a teacher has closed every integrity review on this attempt (R4, §13).

        True only when at least one integrity item exists and none is outside
        :data:`_TEACHER_CLOSED` — so an open or ``withdrawn`` item keeps the
        hold, and closing the plagiarism item does not clear an open
        AI-detection one. Filters on **reason as well as status**: a resolved
        low-confidence item says nothing about an integrity finding.
        """
        integrity_items = select(ReviewQueueItem.id).where(
            ReviewQueueItem.attempt_id == attempt_id,
            ReviewQueueItem.reason.in_(_INTEGRITY_REASONS),
        )
        still_pending = integrity_items.where(ReviewQueueItem.status.not_in(_TEACHER_CLOSED))
        return bool(
            session.scalar(select(sa.and_(integrity_items.exists(), ~still_pending.exists())))
        )

    def _withdraw_open_items(
        self, session: Session, attempt_ids: list[uuid.UUID], now: datetime
    ) -> list[uuid.UUID]:
        """Flip every open review item on these attempts to ``withdrawn`` at ``now``.

        One conditional UPDATE, so an item a teacher closes concurrently is
        either closed first (and left alone) or withdrawn — never both.
        ``resolved_by`` is untouched: a student's delete is not a teacher's
        judgement.
        """
        withdrawn = session.scalars(
            sa.update(ReviewQueueItem)
            .where(
                ReviewQueueItem.attempt_id.in_(attempt_ids),
                ReviewQueueItem.status == ReviewStatus.open,
            )
            # Exactly the attempts' deleted_at — restore selects on this equality.
            .values(status=ReviewStatus.withdrawn, withdrawn_at=now)
            .returning(ReviewQueueItem.id),
            execution_options={"synchronize_session": False},
        ).all()
        return sorted(withdrawn)


__all__ = [
    "DeletedPaper",
    "PaperDeletionError",
    "PaperDeletionService",
    "PaperNotDeletableError",
    "PaperNotFoundError",
    "PaperNotRestorableError",
    "paper_label",
]
