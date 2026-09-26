"""Paper deletion, a student's and a teacher's (design ``2026-09-22-paper-deletion-design.md``).

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

from lemely.core.deletion import (
    integrity_hold_until,
    is_within_restore_window,
    restore_deadline,
    restore_floor,
)
from lemely.db.models.attempts import Attempt, QuestionResult, Upload
from lemely.db.models.enums import (
    SESSION_MONTH_LABELS,
    AttemptOrigin,
    ReviewReason,
    ReviewStatus,
    UploadStatus,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.models.teacher_papers import TeacherPaper
from lemely.db.review_repo import console_paper_label
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

_NOT_RESTORABLE_MESSAGE = "This paper can no longer be restored."

#: Why a console run deleted mid-flight stopped, shown if the paper is restored.
_RUN_STOPPED_BY_DELETE = "Marking stopped when this paper was deleted. Re-run marking to try again."


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


@dataclass(frozen=True, slots=True)
class DeletedPaperSummary:
    """One row of a student's recently-deleted list: one per upload (R7).

    No ``withdrawn_item_ids``: a list row is read, never acted on the way
    :class:`DeletedPaper` is by the undo toast, so it carries nothing the
    listing itself does not show.
    """

    attempt_id: uuid.UUID
    """The upload's newest attempt, by ``recorded_at``: what labels the row."""
    subject_code: str | None
    paper_label: str
    deleted_at: datetime
    restore_deadline: datetime


@dataclass(frozen=True, slots=True)
class DeletedTeacherPaper:
    """One deleted grading-console paper: the outcome of a delete, or a list row (R2).

    Not :class:`DeletedPaper`: a console paper has no attempt, no subject code
    and no siblings, and its name is the console's own card label.
    """

    paper_id: uuid.UUID
    label: str
    deleted_at: datetime
    restore_deadline: datetime


def paper_label(attempt: Attempt) -> str:
    """A human name for the paper, e.g. ``"0625 Paper 4, May/June 2024"``.

    Uses :data:`SESSION_MONTH_LABELS`, the same lookup ``attempt_to_record``
    uses for ``ExamMetadata``, so the paper reads the same here as in history.
    Missing parts are dropped rather than filled: ``"Paper 4, May/June 2024"``
    with no subject, ``"0625, May/June"`` with no paper number or year, and
    ``"Past paper"`` only when neither subject nor paper number is known.
    """
    name = " ".join(
        part
        for part in (
            attempt.subject_code,
            f"Paper {attempt.paper_number}" if attempt.paper_number is not None else None,
        )
        if part
    )
    session = " ".join(
        part
        for part in (
            SESSION_MONTH_LABELS[attempt.session_month]
            if attempt.session_month is not None
            else None,
            str(attempt.session_year) if attempt.session_year is not None else None,
        )
        if part
    )
    return ", ".join(part for part in (name or "Past paper", session) if part)


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


class PaperDeletionService:
    """Soft-deletes a student's own uploaded paper, or restores it, in one transaction."""

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

            # The upload is locked before its attempts are read, never after:
            # a marking run persists a new attempt under this same lock
            # (``attempt_repo._lock_live_upload``). Reading the siblings first
            # would miss an attempt committed while this waited on the upload,
            # and leave it live on a deleted upload.
            upload = self._lock_upload(session, upload_id)
            siblings = self._lock_siblings(session, upload_id)
            addressed = next((a for a in siblings if a.id == parsed_id), None)
            if addressed is None or addressed.user_id != owner or addressed.deleted_at is not None:
                raise PaperNotFoundError("No such paper")
            # Nothing in the schema ties attempts.user_id to uploads.user_id, so
            # a foreign attempt on this upload is refused rather than stamped.
            if any(a.user_id != owner for a in siblings):
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
            # A run deleted mid-flight leaves ``processing`` with nothing to end
            # it: a refused persist skips ``set_status``, and ``set_status`` cannot
            # see a deleted row. Restored, it would read as marking and shadow a
            # real run. Under the upload lock any concurrent run has either
            # committed its attempt or will be refused, and ``complete`` is
            # justified because the upload holds at least one completed
            # attempt: the addressed one.
            if upload.status is UploadStatus.processing:
                upload.status = UploadStatus.complete
            # An upload already deleted keeps its instant: restore matches its
            # siblings on ``deleted_at`` equality, so re-stamping would strand them.
            if upload.deleted_at is None:
                upload.deleted_at = now
                # ux_uploads_user_idempotency survives the soft delete, so a
                # re-upload of the same scan would collide with a row the
                # student cannot see.
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

    def restore(self, user_id: str, attempt_id: str) -> None:
        """Undo the deletion of ``attempt_id``'s upload inside the retention window.

        The unit is the upload, as for :meth:`delete` (R7): every attempt whose
        ``deleted_at`` equals the upload's comes back with it, and an attempt
        deleted at another instant stays deleted. Reopens precisely the review
        items this deletion withdrew, matched on ``withdrawn_at`` equal to that
        instant, keeping their ids and ``created_at`` so they sort where they
        always did. Without the reopen, delete-then-restore returns the paper
        and silently drops the teacher's queue item — for an integrity item past
        D8's hold, a student clearing their own flag (design 2026-09-22 §6).

        The upload's ``idempotency_key`` stays ``NULL``: delete released it so a
        re-upload of the same scan could succeed, and a key that may already
        belong to another row cannot be reclaimed.

        Locks in :meth:`delete`'s order — upload, then attempts by id, then
        review items — which is also ``AttemptRepository._persist``'s upload-first
        order. Any other order is a lock cycle with one of them.

        Raises:
            PaperNotFoundError: no deleted attempt with this id belongs to
                ``user_id`` (a live paper, a malformed id, another student's),
                or an attempt this restore would revive belongs to someone else.
            PaperNotRestorableError: the retention window has passed, or the
                attempt was not deleted together with its upload, so undoing
                that deletion would not bring it back.
        """
        owner = _parse_uuid(user_id)
        parsed_id = _parse_uuid(attempt_id)
        if owner is None or parsed_id is None:
            raise PaperNotFoundError("No such paper")
        now = datetime.now(UTC)

        with self._sessionmaker.begin() as session:
            # Unlocked, only to learn the upload; the checks that count are
            # repeated on the locked copies below.
            addressed = session.scalars(
                select(Attempt)
                .where(Attempt.id == parsed_id)
                .execution_options(**{INCLUDE_DELETED: True})
            ).one_or_none()
            if (
                addressed is None
                or addressed.user_id != owner
                or addressed.deleted_at is None
                or addressed.upload_id is None
            ):
                raise PaperNotFoundError("No such paper")
            upload_id = addressed.upload_id

            upload = self._lock_upload(session, upload_id)
            siblings = self._lock_siblings(session, upload_id)
            addressed = next((a for a in siblings if a.id == parsed_id), None)
            if addressed is None or addressed.user_id != owner or addressed.deleted_at is None:
                raise PaperNotFoundError("No such paper")

            instant = upload.deleted_at
            if instant is None or addressed.deleted_at != instant:
                raise PaperNotRestorableError(_NOT_RESTORABLE_MESSAGE)
            if not is_within_restore_window(instant, now):
                raise PaperNotRestorableError(_NOT_RESTORABLE_MESSAGE)
            revived = [a for a in siblings if a.deleted_at == instant]
            if any(a.user_id != owner for a in revived):
                raise PaperNotFoundError("No such paper")

            for sibling in revived:
                sibling.deleted_at = None
            upload.deleted_at = None
            self._reopen_withdrawn_items(session, [a.id for a in revived], instant)

    def list_deleted(self, user_id: str) -> list[DeletedPaperSummary]:
        """This student's still-restorable deletions, one row per upload, newest first.

        One of three permitted callers of ``include_deleted``, alongside
        :meth:`delete` and :meth:`restore`. Only an attempt stamped at the
        same instant as its upload is listed (Task 6 review): an attempt
        deleted at another instant would offer an Undo that :meth:`restore`
        answers with :class:`PaperNotRestorableError`. Deadlines come from the
        upload's own instant, and a row past the restore window is omitted —
        it is waiting on purge, and no countdown there is honest about it.
        """
        owner = _parse_uuid(user_id)
        if owner is None:
            return []
        now = datetime.now(UTC)
        floor = restore_floor(now)
        stmt = (
            select(Attempt)
            .join(Upload, Upload.id == Attempt.upload_id)
            .where(
                Attempt.user_id == owner,
                Attempt.deleted_at.is_not(None),
                Attempt.deleted_at == Upload.deleted_at,
                Upload.deleted_at > floor,
            )
            .order_by(Attempt.upload_id, Attempt.recorded_at.desc(), Attempt.id.desc())
            .execution_options(**{INCLUDE_DELETED: True})
        )
        with self._sessionmaker() as session:
            attempts = session.scalars(stmt).all()

        newest_by_upload: dict[uuid.UUID, Attempt] = {}
        for a in attempts:
            # The join and the equality filter above guarantee both are set;
            # the check is only to narrow the type for what follows.
            if a.upload_id is None or a.deleted_at is None:
                continue
            newest_by_upload.setdefault(a.upload_id, a)  # first seen per upload = newest

        rows = [
            DeletedPaperSummary(
                attempt_id=a.id,
                subject_code=a.subject_code,
                paper_label=paper_label(a),
                deleted_at=a.deleted_at,
                restore_deadline=restore_deadline(a.deleted_at),
            )
            for a in newest_by_upload.values()
            if a.deleted_at is not None
        ]
        rows.sort(key=lambda row: (row.deleted_at, row.attempt_id), reverse=True)
        return rows

    def assigned_teachers_for(
        self, item_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, uuid.UUID | None]:
        """Return each withdrawn item's ``assigned_teacher_id``, keyed by item id.

        Reads :class:`ReviewQueueItem` alone — never joins to the ``Attempt``
        it belongs to. A caller notifying teachers about its own deletion
        already knows the student (it is the caller), so the one fact still
        needed from the withdrawn item is who, if anyone, was assigned it;
        nothing here touches the now-soft-deleted attempt, so
        :data:`~lemely.db.session.INCLUDE_DELETED` is not needed either. An
        id with no matching row (already purged, or never existed) is simply
        absent from the result rather than raising.
        """
        if not item_ids:
            return {}
        with self._sessionmaker() as session:
            rows = session.execute(
                select(ReviewQueueItem.id, ReviewQueueItem.assigned_teacher_id).where(
                    ReviewQueueItem.id.in_(item_ids)
                )
            ).all()
            return {row.id: row.assigned_teacher_id for row in rows}

    def _lock_upload(self, session: Session, upload_id: uuid.UUID) -> Upload:
        """Lock the upload row, deleted or not, raising if it is gone.

        A concurrent purge could remove the upload between the caller's
        unlocked read and this lock; that is a 404, not a crash on
        ``Result.one()``'s ``NoResultFound``.
        """
        upload = session.scalars(
            select(Upload)
            .where(Upload.id == upload_id)
            .with_for_update()
            .execution_options(**{INCLUDE_DELETED: True}, populate_existing=True)
        ).one_or_none()
        if upload is None:
            raise PaperNotFoundError("No such paper")
        return upload

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

        Never both a teacher close and a withdrawal on one item. That guarantee
        comes from the **attempt row lock**, not from this UPDATE alone. The
        siblings are locked ``FOR UPDATE`` before this runs, and a teacher's
        close takes the same lock (``review_repo._find_any_item(for_update=True)``),
        so the two are serialized. If the close commits first, the
        ``status == open`` condition here skips its item. If this delete
        commits first, the teacher's locked read re-evaluates the loader
        criterion on the now-deleted attempt, finds nothing, and the close is
        refused — the teacher side reads the item's status unlocked, so without
        the lock it would overwrite ``withdrawn``. Removing either lock
        reopens the race.
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

    def _reopen_withdrawn_items(
        self, session: Session, attempt_ids: list[uuid.UUID], deleted_at: datetime
    ) -> None:
        """Reopen the items on these attempts that the deletion at ``deleted_at`` withdrew.

        The inverse of :meth:`_withdraw_open_items`, under the same attempt row
        locks. The ``withdrawn_at`` equality is what keeps a teacher's earlier
        dismissal, or an item withdrawn by some other deletion, out of the
        reopened set.
        """
        session.execute(
            sa.update(ReviewQueueItem)
            .where(
                ReviewQueueItem.attempt_id.in_(attempt_ids),
                ReviewQueueItem.status == ReviewStatus.withdrawn,
                ReviewQueueItem.withdrawn_at == deleted_at,
            )
            .values(status=ReviewStatus.open, withdrawn_at=None),
            execution_options={"synchronize_session": False},
        )


class TeacherPaperDeletionService:
    """Soft-deletes a teacher's own grading-console paper, or restores it (R2, §2.2).

    The student flow's shape, less what a console paper does not have: no
    attempt, so nothing to cascade or keep in step; no integrity hold, because
    ``student_id`` is always NULL and D8 protects evidence *about a student*;
    and the owner is ``uploaded_by``. A school admin who can see a teacher's
    paper still cannot delete it — it is the uploader's.

    **Lock order: the ``teacher_papers`` row, then its review items.**
    :meth:`~lemely.db.teacher_paper_repo.TeacherPaperRepository.finish` takes
    the same row lock before it writes a report or queues items, and so does a
    teacher closing a console item
    (``review_repo._find_any_item(for_update=True)``). So a run finishing, a
    review closing and a delete serialize on one row, and a withdrawn item is
    never also resolved.
    """

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def delete(self, user_id: str, paper_id: str) -> DeletedTeacherPaper:
        """Delete the console paper ``paper_id`` and withdraw its open review items.

        Every open item on the paper is withdrawn with ``withdrawn_at`` equal to
        the paper's ``deleted_at`` — the equality :meth:`restore` selects on. A
        run still in flight is ended here: its ``finish`` will be refused, and
        nothing else would move the row out of ``processing``.

        Raises:
            PaperNotFoundError: no live console paper with this id was uploaded
                by ``user_id`` (including a malformed id, or another teacher's).
        """
        owner = _parse_uuid(user_id)
        parsed_id = _parse_uuid(paper_id)
        if owner is None or parsed_id is None:
            raise PaperNotFoundError("No such paper")
        now = datetime.now(UTC)

        with self._sessionmaker.begin() as session:
            paper = self._lock_paper(session, parsed_id)
            if paper.uploaded_by != owner or paper.deleted_at is not None:
                raise PaperNotFoundError("No such paper")
            paper.deleted_at = now
            if paper.status is UploadStatus.processing:
                # A regrade keeps the previous run's report until it finishes,
                # and that report is still a complete result; a first run has
                # nothing, so it failed — which leaves it claimable on restore.
                if paper.report_json is not None:
                    paper.status = UploadStatus.complete
                else:
                    paper.status = UploadStatus.failed
                    paper.error = _RUN_STOPPED_BY_DELETE
                # The run's position is meaningless once it cannot finish.
                paper.stage = None
                paper.progress_index = None
                paper.progress_total = None
            self._withdraw_console_items(session, parsed_id, now)
            return DeletedTeacherPaper(
                paper_id=paper.id,
                label=console_paper_label(paper),
                deleted_at=now,
                restore_deadline=restore_deadline(now),
            )

    def restore(self, user_id: str, paper_id: str) -> None:
        """Undo the deletion of ``paper_id`` inside the retention window.

        Reopens precisely the review items that deletion withdrew, matched on
        ``withdrawn_at`` equal to the paper's ``deleted_at``, keeping their ids
        and ``created_at``.

        Raises:
            PaperNotFoundError: no deleted console paper with this id was
                uploaded by ``user_id`` (a live paper, a malformed id, another
                teacher's).
            PaperNotRestorableError: the retention window has passed.
        """
        owner = _parse_uuid(user_id)
        parsed_id = _parse_uuid(paper_id)
        if owner is None or parsed_id is None:
            raise PaperNotFoundError("No such paper")
        now = datetime.now(UTC)

        with self._sessionmaker.begin() as session:
            paper = self._lock_paper(session, parsed_id)
            instant = paper.deleted_at
            if paper.uploaded_by != owner or instant is None:
                raise PaperNotFoundError("No such paper")
            if not is_within_restore_window(instant, now):
                raise PaperNotRestorableError(_NOT_RESTORABLE_MESSAGE)
            paper.deleted_at = None
            session.execute(
                sa.update(ReviewQueueItem)
                .where(
                    ReviewQueueItem.teacher_paper_id == parsed_id,
                    ReviewQueueItem.status == ReviewStatus.withdrawn,
                    ReviewQueueItem.withdrawn_at == instant,
                )
                .values(status=ReviewStatus.open, withdrawn_at=None),
                execution_options={"synchronize_session": False},
            )

    def list_deleted(self, user_id: str) -> list[DeletedTeacherPaper]:
        """This teacher's still-restorable console deletions, newest first.

        A row past the restore window is omitted, as in the student list: it is
        waiting on purge and :meth:`restore` would refuse it.
        """
        owner = _parse_uuid(user_id)
        if owner is None:
            return []
        floor = restore_floor(datetime.now(UTC))
        stmt = (
            select(TeacherPaper)
            .where(
                TeacherPaper.uploaded_by == owner,
                TeacherPaper.deleted_at.is_not(None),
                TeacherPaper.deleted_at > floor,
            )
            .order_by(TeacherPaper.deleted_at.desc(), TeacherPaper.id.desc())
            .execution_options(**{INCLUDE_DELETED: True})
        )
        with self._sessionmaker() as session:
            return [
                DeletedTeacherPaper(
                    paper_id=paper.id,
                    label=console_paper_label(paper),
                    deleted_at=paper.deleted_at,
                    restore_deadline=restore_deadline(paper.deleted_at),
                )
                for paper in session.scalars(stmt)
                if paper.deleted_at is not None
            ]

    def _lock_paper(self, session: Session, paper_id: uuid.UUID) -> TeacherPaper:
        """Lock the paper row, deleted or not; a missing or purged row is a 404."""
        paper = session.scalars(
            select(TeacherPaper)
            .where(TeacherPaper.id == paper_id)
            .with_for_update()
            .execution_options(**{INCLUDE_DELETED: True}, populate_existing=True)
        ).one_or_none()
        if paper is None:
            raise PaperNotFoundError("No such paper")
        return paper

    def _withdraw_console_items(self, session: Session, paper_id: uuid.UUID, now: datetime) -> None:
        """Flip every open review item on this paper to ``withdrawn`` at ``now``.

        Under the paper row lock, so a teacher's close and this withdrawal
        never both land (see the class docstring). ``resolved_by`` is untouched.
        Nothing is returned: a teacher deleting their own console paper
        notifies nobody, unlike a student's deletion.
        """
        session.execute(
            sa.update(ReviewQueueItem)
            .where(
                ReviewQueueItem.teacher_paper_id == paper_id,
                ReviewQueueItem.status == ReviewStatus.open,
            )
            .values(status=ReviewStatus.withdrawn, withdrawn_at=now),
            execution_options={"synchronize_session": False},
        )


__all__ = [
    "DeletedPaper",
    "DeletedPaperSummary",
    "DeletedTeacherPaper",
    "PaperDeletionError",
    "PaperDeletionService",
    "PaperNotDeletableError",
    "PaperNotFoundError",
    "PaperNotRestorableError",
    "TeacherPaperDeletionService",
    "paper_label",
]
