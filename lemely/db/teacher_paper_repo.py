"""Teacher paper persistence (spec 2026-09-03 §4.2). Only writer of ``teacher_papers``.

It is also the writer of the **console-sourced** half of ``review_queue``
(migration ``0034``): :meth:`TeacherPaperRepository.finish` stores a finished
run's report and queues that run's flagged questions in one transaction. That
pairing is the point — the grading console derives a paper's "Review" badge
from ``report_json`` while the review queue lists ``review_queue`` rows, so
writing one without the other is exactly how a flagged paper came to show
"Review" on its card while the queue stayed empty.

:class:`TeacherPaperRepository` replaces the in-process ``_PaperStore`` that
backed the teacher grading console before this table existed: every field the
grading worker mutates on a run is a column, so any Cloud Run instance can
answer the polled routes from the row, and a restart loses nothing. Two
things follow directly from that:

1. **``claim_run`` is one conditional ``UPDATE``, not a read then a write.**
   Cloud Run may scale the teacher API to more than one instance, and two of
   them can receive the regrade request for the same paper at nearly the same
   moment. The claim has to be a single statement whose ``WHERE`` clause and
   ``SET`` clause run under the same row lock, so Postgres — not a Python
   ``if`` — decides which caller's update actually matches zero-or-one row.
   The loser's ``UPDATE`` reevaluates the (by-then-committed) row and matches
   nothing, so ``rowcount`` is the only signal callers need: exactly one
   claimer sees ``True``.
2. **A ``processing`` row is reclaimable once it goes stale.** ``updated_at``
   moves on every write this repository makes to a row (``set_stage``,
   ``set_progress``, and so on), so it is the run's liveness signal. A row
   stuck in ``processing`` past ``stale_after`` — a dead worker, a crashed
   instance — is exactly as claimable as a fresh ``pending`` row; there is no
   separate "abandoned" state to model.

**Visibility (DS11)** is enforced inside the query, never filtered on rows
already fetched: a viewer sees a paper if they uploaded it, if they hold a
``school_admin`` membership in a school where the uploader holds a
``teacher`` membership, or if their platform role is ``platform_admin``.
:meth:`get` is the one exception — it has **no** visibility filter, because
its only caller is the grading worker acting on the run it already claimed,
not a person browsing the console; giving it a filter would make a background
job depend on who happened to trigger it.

There is no ORM ``relationship()`` between :class:`~lemely.db.models.teacher_papers.TeacherPaper`
and :class:`~lemely.db.models.users.User`, in either direction — Task 4's
review flagged this specifically. Every method here reaches ``uploaded_by``
and ``student_id`` as plain FK columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol, cast

import sqlalchemy as sa
from sqlalchemy import or_, select

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD, AccuracyReport, ExamMetadata
from lemely.db.models.enums import (
    MembershipRole,
    ReviewReason,
    ReviewStatus,
    Role,
    UploadStatus,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.models.orgs import SchoolMembership
from lemely.db.models.teacher_papers import TeacherPaper

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.sql import ColumnElement


class _HasRowcount(Protocol):
    """The one attribute :func:`_rowcount` needs off a DML result."""

    @property
    def rowcount(self) -> int:
        """Number of rows the statement affected."""


def _rowcount(result: object) -> int:
    """Rows affected by an UPDATE.

    ``Session.execute`` is typed as returning ``Result``, which has no
    ``rowcount``; what a DML statement actually returns at runtime is a
    ``CursorResult``, which does. Narrowing through a one-attribute
    ``Protocol`` (matching ``lemely/db/notification_repo.py``) rather than
    ``cast("CursorResult[Any]", ...)`` keeps this inside mypy's
    no-explicit-``Any`` rule.
    """
    return int(cast("_HasRowcount", result).rowcount or 0)


@dataclass(frozen=True, slots=True)
class TeacherPaperRow:
    """Detached snapshot of a paper. ``stale`` is computed against the repo's window."""

    id: uuid.UUID
    uploaded_by: uuid.UUID
    student_id: uuid.UUID | None
    storage_path: str
    scheme_storage_path: str | None
    original_filename: str | None
    content_type: str | None
    status: UploadStatus
    stage: str | None
    progress: tuple[int, int] | None
    metadata: ExamMetadata | None
    mark_scheme: MarkScheme | None
    report: AccuracyReport | None
    error: str | None
    run_started_at: datetime | None
    created_at: datetime
    updated_at: datetime
    stale: bool


def _review_items_for(paper_id: uuid.UUID, report: AccuracyReport) -> Iterator[ReviewQueueItem]:
    """Yield one open review row per flagged question of a console-graded paper.

    Deliberately the same three-reason rule
    ``AttemptRepository.persist_correction`` applies to a student attempt, so
    the two sources cannot disagree about what "needs review" means:

    * ``low_confidence`` when the **marking** side asked for review — a real
      low confidence score, or ``needs_teacher_review`` set for a structural
      reason. A question that is *purely* integrity-flagged is excluded here,
      because ``apply_integrity_checks`` forces ``needs_teacher_review`` True
      and that would mint a duplicate, mislabelled row alongside the specific
      one below.
    * ``plagiarism_flag`` / ``ai_detection_flag`` per integrity flag actually
      raised. ``lemely.web.services.grading.grade_paper`` runs
      ``apply_integrity_checks`` on the console path too, so these are as real
      here as on a student submission.

    ``question_result_id`` stays NULL — a console paper has no
    ``question_results`` rows — and ``question_id`` carries the mark scheme's
    own id instead (migration ``0034``).
    """
    for question in report.correction.questions:
        marking_flagged = question.needs_teacher_review and not (
            question.plagiarism_flagged or question.ai_detection_flagged
        )
        if marking_flagged or question.confidence_score < REVIEW_CONFIDENCE_THRESHOLD:
            yield ReviewQueueItem(
                teacher_paper_id=paper_id,
                question_id=question.question_id,
                reason=ReviewReason.low_confidence,
            )
        if question.plagiarism_flagged:
            yield ReviewQueueItem(
                teacher_paper_id=paper_id,
                question_id=question.question_id,
                reason=ReviewReason.plagiarism_flag,
            )
        if question.ai_detection_flagged:
            yield ReviewQueueItem(
                teacher_paper_id=paper_id,
                question_id=question.question_id,
                reason=ReviewReason.ai_detection_flag,
            )


def teacher_paper_visible(viewer_id: uuid.UUID, viewer_role: Role) -> ColumnElement[bool]:
    """The DS11 visibility predicate for :class:`TeacherPaper`, as a WHERE clause.

    Module-level rather than a private method because
    :class:`~lemely.db.review_repo.ReviewService` scopes console-sourced
    review-queue rows by the *same* rule (migration ``0034``): a console review
    item is visible exactly when its paper is. Two definitions of "visible
    paper" that could drift apart is precisely the bug this avoids — the
    review queue must never show a paper the grading console would not.
    """
    if viewer_role is Role.platform_admin:
        return sa.true()
    own = TeacherPaper.uploaded_by == viewer_id
    if viewer_role is not Role.school_admin:
        return own
    admin_schools = select(SchoolMembership.school_id).where(
        SchoolMembership.user_id == viewer_id,
        SchoolMembership.membership_role == MembershipRole.school_admin,
    )
    teachers = select(SchoolMembership.user_id).where(
        SchoolMembership.school_id.in_(admin_schools),
        SchoolMembership.membership_role == MembershipRole.teacher,
    )
    return or_(own, TeacherPaper.uploaded_by.in_(teachers))


class TeacherPaperRepository:
    """CRUD plus the cross-instance run claim for :class:`TeacherPaper`."""

    def __init__(self, session_factory: sessionmaker[Session], *, stale_after: timedelta) -> None:
        """Bind to a ``sessionmaker``.

        ``stale_after`` (``GradingSettings.stale_run_after_seconds``) is
        injected rather than read from settings directly, so tests can use a
        short window instead of sleeping (spec §4.2).
        """
        self._sm = session_factory
        self._stale_after = stale_after

    # -- visibility (DS11) --------------------------------------------------

    def _visible(self, viewer_id: uuid.UUID, viewer_role: Role) -> ColumnElement[bool]:
        return teacher_paper_visible(viewer_id, viewer_role)

    def get(self, paper_id: uuid.UUID) -> TeacherPaperRow | None:
        """The paper with no visibility filter — for the grading worker, never a route."""
        with self._sm() as session:
            row = session.get(TeacherPaper, paper_id)
            return None if row is None else self._snapshot(row)

    def get_visible(
        self, paper_id: uuid.UUID, *, viewer_id: uuid.UUID, viewer_role: Role
    ) -> TeacherPaperRow | None:
        """The paper if the viewer may see it, else ``None`` (never an existence oracle)."""
        stmt = select(TeacherPaper).where(
            TeacherPaper.id == paper_id, self._visible(viewer_id, viewer_role)
        )
        with self._sm() as session:
            row = session.scalars(stmt).one_or_none()
            return None if row is None else self._snapshot(row)

    def list_visible(self, *, viewer_id: uuid.UUID, viewer_role: Role) -> list[TeacherPaperRow]:
        """Every paper the viewer may see, newest first."""
        stmt = (
            select(TeacherPaper)
            .where(self._visible(viewer_id, viewer_role))
            .order_by(TeacherPaper.created_at.desc())
        )
        with self._sm() as session:
            return [self._snapshot(r) for r in session.scalars(stmt)]

    # -- lifecycle ------------------------------------------------------------

    def create(
        self,
        *,
        paper_id: uuid.UUID,
        uploaded_by: uuid.UUID,
        storage_path: str,
        scheme_storage_path: str | None,
        original_filename: str | None,
        content_type: str | None,
        byte_size: int | None,
    ) -> uuid.UUID:
        """Insert a ``pending`` row under the caller-generated ``paper_id``."""
        with self._sm.begin() as session:
            session.add(
                TeacherPaper(
                    id=paper_id,
                    uploaded_by=uploaded_by,
                    storage_path=storage_path,
                    scheme_storage_path=scheme_storage_path,
                    original_filename=original_filename,
                    content_type=content_type,
                    byte_size=byte_size,
                )
            )
        return paper_id

    def claim_run(self, paper_id: uuid.UUID) -> bool:
        """Atomically move the row to ``processing``; ``True`` iff this caller now owns the run.

        One conditional UPDATE, so two instances (or two threads) racing for
        the same paper cannot both win — the database decides, not a lock
        held in this process. A ``processing`` row is reclaimable only once
        its ``updated_at`` is older than the stale window (a dead run).
        """
        cutoff = datetime.now(UTC) - self._stale_after
        stmt = (
            sa.update(TeacherPaper)
            .where(
                TeacherPaper.id == paper_id,
                or_(
                    TeacherPaper.status.in_(
                        [UploadStatus.pending, UploadStatus.failed, UploadStatus.complete]
                    ),
                    sa.and_(
                        TeacherPaper.status == UploadStatus.processing,
                        TeacherPaper.updated_at < cutoff,
                    ),
                ),
            )
            .values(
                status=UploadStatus.processing,
                run_started_at=sa.func.now(),
                stage="detect",
                progress_index=None,
                progress_total=None,
                error=None,
            )
        )
        with self._sm.begin() as session:
            result = session.execute(stmt)
            return _rowcount(result) == 1

    def set_stage(self, paper_id: uuid.UUID, stage: str) -> None:
        """Move to ``stage`` and clear the counter (``updated_at`` moves — liveness)."""
        self._update(paper_id, stage=stage, progress_index=None, progress_total=None)

    def set_progress(self, paper_id: uuid.UUID, index: int, total: int) -> None:
        """Record the per-stage counter."""
        self._update(paper_id, progress_index=index, progress_total=total)

    def set_metadata(self, paper_id: uuid.UUID, metadata: ExamMetadata) -> None:
        """Cache the detected exam metadata."""
        self._update(paper_id, metadata_json=metadata.model_dump(mode="json"))

    def set_mark_scheme(self, paper_id: uuid.UUID, scheme: MarkScheme) -> None:
        """Cache the resolved scheme so a regrade need not re-parse."""
        self._update(paper_id, mark_scheme_json=scheme.model_dump(mode="json"))

    def finish(self, paper_id: uuid.UUID, report: AccuracyReport) -> None:
        """Terminal success: store the report **and** queue its flagged questions.

        The two writes share one transaction on purpose. A paper whose card
        says "Review" while the review queue holds nothing for it is exactly
        the split this repository used to produce — the console read
        ``report_json`` and the queue read ``review_queue``, and only the
        student path ever wrote the latter. Committing the report without its
        review rows would reopen that gap on any crash in between.
        """
        with self._sm.begin() as session:
            session.execute(
                sa.update(TeacherPaper)
                .where(TeacherPaper.id == paper_id)
                .values(
                    status=UploadStatus.complete,
                    report_json=report.model_dump(mode="json"),
                    error=None,
                    progress_index=None,
                    progress_total=None,
                )
            )
            # A regrade calls `finish` again on the same paper. Clear this
            # paper's still-open rows first so the queue reflects the run that
            # just finished, not the union of every run ever made. Rows a
            # teacher already resolved or dismissed are left alone: that
            # decision is a record, and re-marking must not silently undo it.
            session.execute(
                sa.delete(ReviewQueueItem).where(
                    ReviewQueueItem.teacher_paper_id == paper_id,
                    ReviewQueueItem.status == ReviewStatus.open,
                )
            )
            for item in _review_items_for(paper_id, report):
                session.add(item)

    def fail(self, paper_id: uuid.UUID, error: str) -> None:
        """Terminal failure, with the reason the console shows."""
        self._update(paper_id, status=UploadStatus.failed, error=error)

    # -- helpers --------------------------------------------------------------

    def _update(self, paper_id: uuid.UUID, **values: object) -> None:
        with self._sm.begin() as session:
            session.execute(
                sa.update(TeacherPaper).where(TeacherPaper.id == paper_id).values(**values)
            )

    def _snapshot(self, row: TeacherPaper) -> TeacherPaperRow:
        progress = (
            (row.progress_index, row.progress_total)
            if row.progress_index is not None and row.progress_total is not None
            else None
        )
        stale = (
            row.status is UploadStatus.processing
            and row.updated_at < datetime.now(UTC) - self._stale_after
        )
        return TeacherPaperRow(
            id=row.id,
            uploaded_by=row.uploaded_by,
            student_id=row.student_id,
            storage_path=row.storage_path,
            scheme_storage_path=row.scheme_storage_path,
            original_filename=row.original_filename,
            content_type=row.content_type,
            status=row.status,
            stage=row.stage,
            progress=progress,
            metadata=ExamMetadata.model_validate(row.metadata_json) if row.metadata_json else None,
            mark_scheme=MarkScheme.model_validate(row.mark_scheme_json)
            if row.mark_scheme_json
            else None,
            report=AccuracyReport.model_validate(row.report_json) if row.report_json else None,
            error=row.error,
            run_started_at=row.run_started_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            stale=stale,
        )


__all__ = ["TeacherPaperRepository", "TeacherPaperRow", "teacher_paper_visible"]
