"""Review queue + override service — T-07/T-08 backend (P3.4).

Mirrors :mod:`lemely.db.class_repo`'s shape: pure ownership/mutation logic
over a ``sessionmaker``, domain errors mapped to HTTP status codes by a thin
router layer (:mod:`lemely.web.routers.review`), testable against Postgres
with no GoTrue dependency.

**The queue has two sources, and one tenancy rule each** (migration ``0034``).

*Student attempts* — written by ``AttemptRepository.persist_correction`` — are
scoped by the union of every roster the caller may see, the identical rule
:func:`lemely.web.routers.teacher._visible_students` already enforces for every
other student-scoped teacher route (D3.1). :class:`ReviewService` does not
import that function (it lives in the web layer); instead it composes the same
two :class:`~lemely.db.class_repo.ClassService` calls (``list_classes`` +
``roster``) that function does, so the two call sites can never define "visible
student" differently.

*Console papers* — written by ``TeacherPaperRepository.finish`` — are scoped by
:func:`~lemely.db.teacher_paper_repo.teacher_paper_visible`, the same predicate
the grading console itself applies (DS11), for the same
one-definition reason: the review queue must never list a paper the console
would not show. They exist because a grading-console upload is never
attributed to a student (``teacher_papers.student_id`` is always NULL, D1.12)
and so has no ``Attempt`` for the roster rule above to reach — which is exactly
how a console paper could once show "Review" on its card while this queue
stayed empty.

**Neither source has a super-role bypass.** ``platform_admin`` sees no classes
via ``ClassService`` and is therefore empty-scoped on the attempt half
(D1.6/D1.10); the console half excludes it explicitly, because
``teacher_paper_visible`` *does* grant it every paper and inheriting that here
would widen this endpoint rather than fix it. Every out-of-scope access on
either source raises the same :class:`ReviewOwnershipError` (403) carrying no
data, exactly like :class:`~lemely.db.class_repo.ClassOwnershipError`, so
neither half is an existence oracle for the other's rows.

**No new table.** ``review_queue`` (0002) already carries reason / status /
assignment / resolution; ``0034`` only added the second source discriminator
(``teacher_paper_id`` + ``question_id``, with a CHECK that exactly one source
is set). The one piece of new persistent state P3.4 needed is *what the
teacher changed the mark to*, which belongs on the
:class:`~lemely.db.models.attempts.QuestionResult` it corrects (migration
``0005_review_overrides``) — a question can accumulate more than one
review-queue row (e.g. a ``low_confidence`` row and a ``plagiarism_flag`` row
for the same question, see ``AttemptRepository.persist_correction``), but it
has exactly one AI mark and at most one teacher correction. A console-sourced
item has **no** ``QuestionResult`` at all — its marks live inside
``teacher_papers.report_json`` — so it can be accepted as-is or dismissed but
never re-marked, and :meth:`ReviewService.resolve` refuses ``override_marks``
on one outright rather than accepting a correction it would have to drop.

**Overrides recompute the attempt total eagerly**, at the point of mutation,
rather than requiring every reader to know overrides exist. This is the one
choke point instead of patching call sites: :meth:`ReviewService.resolve`
rewrites ``Attempt.awarded_marks`` / ``percentage`` / ``grade`` /
``predicted_grade`` / ``boundary_source`` from the sum of every question's
:attr:`~lemely.db.models.attempts.QuestionResult.effective_marks` the moment an
override lands, using the *same* deterministic boundary lookup
(:class:`~lemely.io.grade_boundaries.GradeBoundaryStore`) the original grade
was computed with (fed by the exam metadata already on the attempt row, so it
resolves to bit-identical boundaries — no drift). Every existing consumer of
``Attempt`` — :class:`~lemely.db.history_repo.DbHistoryStore`, and therefore
every ``PaperRecord``/``StudentHistory`` the student and teacher portals
already read — sees the corrected total with no changes of its own required.

**The same override also recomputes affected** :class:`~lemely.db.models.attempts.WeaknessRecord`
**rows**, not just the attempt total. ``history_repo.attempt_to_record`` builds
``PaperRecord.weak_areas`` straight from ``attempt.weakness_records``, which
were written at persist time from the AI's marks; leaving them untouched
after an override would mean a restored question still counts as "lost" on
the student's weakness list, the T-04 class heatmap
(``aggregate_weaknesses_from_history``), and everything downstream of it —
the exact "corrected on one screen, stale on another" failure D3.3 already
fixed once for "at risk". :meth:`ReviewService._recompute_weakness_records`
re-groups every question's ``effective_marks`` with
:func:`~lemely.core.analytics.group_weak_areas` — the identical
topic-bucketing algorithm ``summarize_weaknesses`` used at persist time — and
diffs the result against what is currently stored: a topic still net-losing
marks is updated in place, a topic newly created a loss gets a fresh row, and
a topic whose lost marks dropped to zero (e.g. the override restored it to
full marks) is **deleted outright**, matching
``summarize_weaknesses``/``aggregate_weaknesses_from_history``'s own rule
that a zero-loss topic is not a weakness at all.

**Dismissing an integrity flag never touches a** :class:`QuestionResult`.
That is not a policy choice enforced by hiding a field later; it is
structural — :meth:`ReviewService.dismiss` only ever writes to the
``ReviewQueueItem`` row (which no student-facing route reads), so "no
student-visible record survives a dismissal" (MISSION §4 / UI-spec §1.4) holds
by construction, not by convention.

**Bulk-approve is skip-and-report, not all-or-nothing.** A batch of
"trivially fine" items (T-07) is exactly the case where one stale/out-of-scope
id should not sink the other nineteen a teacher correctly selected; each id is
independently checked and either accepted or reported with why it was
skipped (``not_found`` / ``forbidden`` / ``already_closed``) — see
:meth:`ReviewService.bulk_approve`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError
from sqlalchemy import select

from lemely.core.analytics import (
    DEFAULT_GRADE_BOUNDARIES,
    WeakAreaInput,
    grade_for_percentage,
    group_weak_areas,
)
from lemely.core.schemas import AccuracyReport, CorrectedQuestion, ExamMetadata
from lemely.db.models.attempts import Attempt, QuestionResult, WeaknessRecord
from lemely.db.models.enums import (
    SESSION_MONTH_LABELS,
    AttemptOrigin,
    BoundarySource,
    ReviewReason,
    ReviewStatus,
    Role,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.models.teacher_papers import TeacherPaper
from lemely.db.teacher_paper_repo import teacher_paper_visible
from lemely.io.grade_boundaries import GradeBoundaryStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.class_repo import ClassService

log = structlog.get_logger(__name__)


class ReviewError(Exception):
    """Base class for review-queue failures."""


class ReviewNotFoundError(ReviewError):
    """No review item exists for the supplied id (→ 404)."""


class ReviewOwnershipError(ReviewError):
    """The caller may not access the target review item (→ 403)."""


class ReviewAlreadyClosedError(ReviewError):
    """The item is not ``open`` (already resolved/dismissed) (→ 409)."""


class ReviewValidationError(ReviewError):
    """The requested mutation is not valid for this item (→ 422)."""


@dataclass(frozen=True, slots=True)
class ReviewQueueRow:
    """One review-queue entry, enriched with the display context T-07 needs.

    Carries **either** source (migration ``0034``), and says which in
    :attr:`source` so a caller never has to infer it from which ids happen to
    be set:

    * ``"student_attempt"`` — ``attempt_id`` and the student/class fields are
      set; ``paper_id`` is ``None``.
    * ``"console_paper"`` — ``paper_id`` is set and ``attempt_id`` is ``None``.
      A grading-console upload is never attributed to a student (D1.12), so
      ``student_id``/``class_id``/``class_name`` are ``None`` rather than
      filled with a plausible-looking guess, and
      :attr:`student_display_name` carries the paper's own label instead.
    """

    item_id: uuid.UUID
    source: str  # "student_attempt" | "console_paper"
    attempt_id: uuid.UUID | None
    paper_id: uuid.UUID | None
    question_result_id: uuid.UUID | None
    student_id: uuid.UUID | None
    student_display_name: str
    class_id: uuid.UUID | None
    class_name: str | None
    subject_code: str | None
    paper_number: int | None
    paper_variant: int | None
    session_month: str | None
    session_year: int | None
    question_id: str | None
    reason: ReviewReason
    status: ReviewStatus
    created_at: datetime
    waiting_hours: float
    ai_awarded_marks: int | None
    maximum_marks: int | None
    confidence_score: float | None


@dataclass(frozen=True, slots=True)
class ReviewItemDetail:
    """T-08's full detail: the row plus the question content and any override."""

    row: ReviewQueueRow
    student_answer: str | None
    expected_answer: str | None
    topic: str | None
    matched_point_ids: list[str]
    feedback: str | None
    marker_source: str | None
    review_reason: str | None
    is_overridden: bool
    teacher_awarded_marks: int | None
    teacher_note: str | None
    teacher_breakdown: dict | None  # type: ignore[type-arg]
    overridden_by: uuid.UUID | None
    overridden_at: datetime | None
    resolution_note: str | None
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class BulkApproveSkip:
    """One id the bulk-approve call declined to touch, and why."""

    item_id: uuid.UUID
    reason: str  # "not_found" | "forbidden" | "already_closed"


@dataclass(frozen=True, slots=True)
class BulkApproveResult:
    """Skip-and-report outcome of a bulk-approve call."""

    approved: list[uuid.UUID]
    skipped: list[BulkApproveSkip]


class ReviewService:
    """Review-queue listing, detail, resolve/override, dismiss, bulk-approve.

    Constructed with a ``sessionmaker`` and the same
    :class:`~lemely.db.class_repo.ClassService` the class routes use — every
    method re-verifies ownership before touching any row; there is no
    super-role bypass (``platform_admin`` sees no classes via ``ClassService``,
    so it is always empty-scoped here too, D1.6/D1.10).
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        class_service: ClassService,
        boundary_store: GradeBoundaryStore | None = None,
    ) -> None:
        """Wire the service to its collaborators.

        ``boundary_store`` defaults to a freshly-loaded
        :class:`~lemely.io.grade_boundaries.GradeBoundaryStore` when omitted.
        """
        self._sessionmaker = sessionmaker
        self._class_service = class_service
        self._boundaries = boundary_store or GradeBoundaryStore()

    # -- Listing --------------------------------------------------------------

    def list_queue(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        *,
        class_id: uuid.UUID | str | None = None,
        reason: str | None = None,
        min_age_hours: float | None = None,
    ) -> list[ReviewQueueRow]:
        """Return every **open** review item across the caller's own students.

        ``class_id`` restricts to one of the caller's classes (a class the
        caller does not own/administer simply yields no rows — never a
        class-existence oracle on a list filter). ``reason`` matches
        :class:`~lemely.db.models.enums.ReviewReason`'s value; an unrecognised
        value yields no matches, never a 500 (mirrors ``teacher_at_risk_list``).
        ``min_age_hours`` keeps only items that have been waiting at least that
        long.
        """
        visible = self._visible_class_map(caller_id, caller_role, class_id_filter=class_id)
        reason_enum: ReviewReason | None = None
        if reason is not None:
            try:
                reason_enum = ReviewReason(reason)
            except ValueError:
                return []
        now = datetime.now(UTC)
        results: list[ReviewQueueRow] = []
        with self._sessionmaker() as session:
            if visible:
                stmt = (
                    select(ReviewQueueItem, Attempt, QuestionResult)
                    .join(Attempt, ReviewQueueItem.attempt_id == Attempt.id)
                    .outerjoin(
                        QuestionResult, ReviewQueueItem.question_result_id == QuestionResult.id
                    )
                    .where(
                        ReviewQueueItem.status == ReviewStatus.open,
                        Attempt.user_id.in_(visible.keys()),
                    )
                    .order_by(ReviewQueueItem.created_at)
                )
                if reason_enum is not None:
                    stmt = stmt.where(ReviewQueueItem.reason == reason_enum)
                for item, attempt, qr in session.execute(stmt).all():
                    class_id_, class_name, display_name = visible[attempt.user_id]
                    results.append(
                        _to_row(item, attempt, qr, class_id_, class_name, display_name, now=now)
                    )
            # Console-sourced items (migration 0034). Scoped by paper
            # visibility, not by class roster: a grading-console upload has no
            # student and therefore no class, so the roster rule that scopes
            # the attempt half above can never match one. Skipped entirely
            # when `class_id` narrows the query — a console paper belongs to
            # no class, so "this class only" excludes it by definition rather
            # than by omission.
            #
            # `platform_admin` is excluded explicitly. `teacher_paper_visible`
            # grants it every paper (DS11, which is the grading console's own
            # rule), but this queue's tenancy has no super-role bypass at all
            # (D1.6/D1.10, module docstring): a platform admin sees no classes
            # via `ClassService` and so sees no attempt-backed items either.
            # Letting the console half through would hand the one role that is
            # deliberately empty-scoped here a view of every teacher's marking
            # — a widening of this endpoint, not a fix to it.
            if class_id is None and _as_role(caller_role) is not Role.platform_admin:
                paper_stmt = (
                    select(ReviewQueueItem, TeacherPaper)
                    .join(TeacherPaper, ReviewQueueItem.teacher_paper_id == TeacherPaper.id)
                    .where(
                        ReviewQueueItem.status == ReviewStatus.open,
                        teacher_paper_visible(_as_uuid(caller_id), _as_role(caller_role)),
                    )
                    .order_by(ReviewQueueItem.created_at)
                )
                if reason_enum is not None:
                    paper_stmt = paper_stmt.where(ReviewQueueItem.reason == reason_enum)
                # One parse per paper, not per row: a single paper commonly
                # contributes several flagged questions, and validating its
                # whole `AccuracyReport` again for each one is pure waste.
                reports: dict[uuid.UUID, AccuracyReport | None] = {}
                for item, paper in session.execute(paper_stmt).all():
                    if paper.id not in reports:
                        reports[paper.id] = _console_report(paper)
                    results.append(_to_console_row(item, paper, now=now, report=reports[paper.id]))
        # Oldest first across both sources — longest-waiting is highest
        # priority, and that ordering must hold over the merged list, not
        # within each half (T-07's "prioritised list").
        results.sort(key=lambda row: row.created_at)
        if min_age_hours is not None:
            results = [row for row in results if row.waiting_hours >= min_age_hours]
        return results

    def get_item(
        self, caller_id: uuid.UUID | str, caller_role: Role | str, item_id: uuid.UUID | str
    ) -> ReviewItemDetail:
        """Return T-08's full detail for one review item.

        Raises:
            ReviewNotFoundError: No item exists with ``item_id`` (404).
            ReviewOwnershipError: The item exists but its attempt's owner is
                not one of the caller's visible students (403).
        """
        visible = self._visible_class_map(caller_id, caller_role)
        with self._sessionmaker() as session:
            item, attempt, qr, paper = self._find_any_item(
                session, item_id, visible, caller_id=caller_id, caller_role=caller_role
            )
            now = datetime.now(UTC)
            if paper is not None:
                return _console_item_detail(item, paper, now=now)
            attempt = _require_attempt(item, attempt)
            class_id_, class_name, display_name = visible[attempt.user_id]
            row = _to_row(item, attempt, qr, class_id_, class_name, display_name, now=now)
        return ReviewItemDetail(
            row=row,
            student_answer=qr.student_answer if qr is not None else None,
            expected_answer=qr.expected_answer if qr is not None else None,
            topic=qr.topic if qr is not None else None,
            matched_point_ids=list(qr.matched_point_ids) if qr is not None else [],
            feedback=qr.feedback if qr is not None else None,
            marker_source=qr.marker_source.value if qr is not None else None,
            review_reason=qr.review_reason if qr is not None else None,
            is_overridden=qr.is_overridden if qr is not None else False,
            teacher_awarded_marks=qr.teacher_awarded_marks if qr is not None else None,
            teacher_note=qr.teacher_note if qr is not None else None,
            teacher_breakdown=qr.teacher_breakdown if qr is not None else None,
            overridden_by=qr.overridden_by if qr is not None else None,
            overridden_at=qr.overridden_at if qr is not None else None,
            resolution_note=item.resolution_note,
            resolved_by=item.resolved_by,
            resolved_at=item.resolved_at,
        )

    # -- Mutations --------------------------------------------------------------

    def resolve(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        item_id: uuid.UUID | str,
        *,
        override_marks: int | None = None,
        breakdown: dict[str, object] | None = None,
        note: str | None = None,
    ) -> ReviewQueueRow:
        """Resolve one open item: accept the AI mark as-is, or override it.

        ``override_marks is None`` accepts the existing mark unchanged (still
        closes the item; ``note`` is recorded as an internal resolution note if
        given). ``override_marks`` supplied records a teacher correction on the
        underlying :class:`~lemely.db.models.attempts.QuestionResult` — clamped
        to ``[0, maximum_marks]`` — and eagerly recomputes the attempt's total
        AND its affected weakness records (see module docstring), labelling the
        mark as a teacher correction and attributing who/when.

        Raises:
            ReviewNotFoundError: No item exists with ``item_id`` (404).
            ReviewOwnershipError: The caller may not access this item (403).
            ReviewAlreadyClosedError: The item is not ``open`` (409).
            ReviewValidationError: ``override_marks`` was supplied but the item
                has no underlying question result — including every
                console-sourced item, which by construction has none — or the
                value is out of range (422).
        """
        caller_uuid = _as_uuid(caller_id)
        visible = self._visible_class_map(caller_id, caller_role)
        with self._sessionmaker() as session, session.begin():
            item, attempt, qr, paper = self._find_any_item(
                session, item_id, visible, caller_id=caller_id, caller_role=caller_role
            )
            if item.status != ReviewStatus.open:
                raise ReviewAlreadyClosedError(
                    f"Review item {item.id} is already {item.status.value}"
                )
            now = datetime.now(UTC)
            if paper is not None:
                # Accept-as-is only. A console paper's marks live inside
                # `teacher_papers.report_json` and there is no
                # `QuestionResult` for `0005_review_overrides` to record a
                # correction on — so an override is refused outright rather
                # than accepted and silently dropped, which would tell the
                # teacher their re-mark landed when nothing changed.
                if override_marks is not None:
                    raise ReviewValidationError(
                        f"Review item {item.id} comes from a grading-console paper, which "
                        f"stores no per-question result to record a mark override on; it can "
                        f"be accepted as-is or dismissed, not re-marked"
                    )
                item.status = ReviewStatus.resolved
                item.resolved_by = caller_uuid
                item.resolved_at = now
                item.resolution_note = note
                session.flush()
                return _to_console_row(item, paper, now=now, report=_console_report(paper))
            attempt = _require_attempt(item, attempt)
            if override_marks is not None:
                if qr is None:
                    raise ReviewValidationError(
                        f"Review item {item.id} has no question result to override"
                    )
                if not (0 <= override_marks <= qr.maximum_marks):
                    raise ReviewValidationError(
                        f"override marks must be between 0 and {qr.maximum_marks}, "
                        f"got {override_marks}"
                    )
                qr.teacher_awarded_marks = override_marks
                qr.teacher_note = note
                qr.teacher_breakdown = breakdown
                qr.overridden_by = caller_uuid
                qr.overridden_at = now
                session.flush()
                results = session.scalars(
                    select(QuestionResult).where(QuestionResult.attempt_id == attempt.id)
                ).all()
                self._recompute_attempt_totals(session, attempt, results)
                self._recompute_weakness_records(session, attempt, results)
            item.status = ReviewStatus.resolved
            item.resolved_by = caller_uuid
            item.resolved_at = now
            item.resolution_note = note
            session.flush()
            class_id_, class_name, display_name = visible[attempt.user_id]
            return _to_row(item, attempt, qr, class_id_, class_name, display_name, now=now)

    def dismiss(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        item_id: uuid.UUID | str,
        *,
        note: str | None = None,
    ) -> ReviewQueueRow:
        """Dismiss an integrity flag. Leaves no student-visible record (see module docstring).

        Restricted to ``plagiarism_flag`` / ``ai_detection_flag`` items —
        UI-spec T-08 ties "dismiss without a record reaching the student"
        specifically to integrity flags; a ``low_confidence``/``manual`` item
        is resolved (accept-as-is), never dismissed.

        Raises:
            ReviewNotFoundError: No item exists with ``item_id`` (404).
            ReviewOwnershipError: The caller may not access this item (403).
            ReviewAlreadyClosedError: The item is not ``open`` (409).
            ReviewValidationError: The item's reason is not an integrity flag (422).
        """
        caller_uuid = _as_uuid(caller_id)
        visible = self._visible_class_map(caller_id, caller_role)
        with self._sessionmaker() as session, session.begin():
            item, attempt, qr, paper = self._find_any_item(
                session, item_id, visible, caller_id=caller_id, caller_role=caller_role
            )
            if item.reason not in (ReviewReason.plagiarism_flag, ReviewReason.ai_detection_flag):
                raise ReviewValidationError(
                    f"Only integrity flags may be dismissed; item {item.id} has "
                    f"reason {item.reason.value}"
                )
            if item.status != ReviewStatus.open:
                raise ReviewAlreadyClosedError(
                    f"Review item {item.id} is already {item.status.value}"
                )
            now = datetime.now(UTC)
            item.status = ReviewStatus.dismissed
            item.resolved_by = caller_uuid
            item.resolved_at = now
            item.resolution_note = note
            session.flush()
            if paper is not None:
                return _to_console_row(item, paper, now=now, report=_console_report(paper))
            attempt = _require_attempt(item, attempt)
            class_id_, class_name, display_name = visible[attempt.user_id]
            return _to_row(item, attempt, qr, class_id_, class_name, display_name, now=now)

    def bulk_approve(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        item_ids: list[uuid.UUID],
    ) -> BulkApproveResult:
        """Accept-as-is every ``open`` id the caller may access; skip the rest.

        Skip-and-report, not all-or-nothing (see module docstring): each id is
        independently either approved or reported skipped with
        ``"not_found"`` / ``"forbidden"`` / ``"already_closed"``. Never applies
        a marks override — bulk-approve is T-07's "trivially fine ones" action
        only.
        """
        caller_uuid = _as_uuid(caller_id)
        visible = self._visible_class_map(caller_id, caller_role)
        approved: list[uuid.UUID] = []
        skipped: list[BulkApproveSkip] = []
        now = datetime.now(UTC)
        with self._sessionmaker() as session, session.begin():
            for item_uuid in item_ids:
                # Reuse the single-item loader so both sources are checked by
                # exactly the rule their own tenancy defines, then translate
                # its exceptions into this call's skip reasons — a batch must
                # never authorise anything a single resolve would refuse.
                try:
                    item, _attempt, _qr, _paper = self._find_any_item(
                        session, item_uuid, visible, caller_id=caller_id, caller_role=caller_role
                    )
                except ReviewNotFoundError:
                    skipped.append(BulkApproveSkip(item_id=item_uuid, reason="not_found"))
                    continue
                except ReviewOwnershipError:
                    skipped.append(BulkApproveSkip(item_id=item_uuid, reason="forbidden"))
                    continue
                if item.status != ReviewStatus.open:
                    skipped.append(BulkApproveSkip(item_id=item_uuid, reason="already_closed"))
                    continue
                item.status = ReviewStatus.resolved
                item.resolved_by = caller_uuid
                item.resolved_at = now
                approved.append(item_uuid)
        return BulkApproveResult(approved=approved, skipped=skipped)

    # -- Internals --------------------------------------------------------------

    def _visible_class_map(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        *,
        class_id_filter: uuid.UUID | str | None = None,
    ) -> dict[uuid.UUID, tuple[uuid.UUID, str, str]]:
        """Map every visible student to their class context.

        ``{student_id: (class_id, class_name, display_name)}`` for every class
        the caller may see (optionally narrowed to one class id) — the same
        roster-union tenancy rule as
        ``lemely.web.routers.teacher._visible_students`` (see module docstring).
        """
        mapping: dict[uuid.UUID, tuple[uuid.UUID, str, str]] = {}
        rows = self._class_service.list_classes(caller_id, caller_role)
        if class_id_filter is not None:
            class_uuid = _as_uuid(class_id_filter)
            rows = [row for row in rows if row.class_id == class_uuid]
        for row in rows:
            for entry in self._class_service.roster(caller_id, caller_role, row.class_id):
                mapping[entry.student_id] = (row.class_id, row.name, entry.display_name)
        return mapping

    def _find_any_item(
        self,
        session: Session,
        item_id: uuid.UUID | str,
        visible: dict[uuid.UUID, tuple[uuid.UUID, str, str]],
        *,
        caller_id: uuid.UUID | str | None = None,
        caller_role: Role | str | None = None,
    ) -> tuple[ReviewQueueItem, Attempt | None, QuestionResult | None, TeacherPaper | None]:
        """Load one item of **either** source, enforcing that source's tenancy.

        Exactly one of ``attempt`` / ``paper`` comes back non-``None``, matching
        ``ck_review_queue_one_source``. An attempt-backed item is checked
        against the caller's roster union; a console-sourced one against the
        same paper-visibility rule the grading console applies
        (:func:`~lemely.db.teacher_paper_repo.teacher_paper_visible`), minus
        the ``platform_admin`` grant this queue does not honour — see
        :meth:`list_queue`. Both failures raise the same
        :class:`ReviewOwnershipError` carrying no data, so neither is an
        existence oracle for the other's rows.

        Raises:
            ReviewNotFoundError: No item exists with ``item_id`` (404).
            ReviewOwnershipError: The caller may not access it (403).
        """
        item_uuid = _as_uuid(item_id)
        item = session.get(ReviewQueueItem, item_uuid)
        if item is None:
            raise ReviewNotFoundError(f"Unknown review item: {item_uuid}")
        if item.teacher_paper_id is not None:
            if caller_id is None or caller_role is None:
                raise ReviewOwnershipError(f"Caller may not access review item {item_uuid}")
            role = _as_role(caller_role)
            if role is Role.platform_admin:
                raise ReviewOwnershipError(f"Caller may not access review item {item_uuid}")
            paper = session.scalars(
                select(TeacherPaper).where(
                    TeacherPaper.id == item.teacher_paper_id,
                    teacher_paper_visible(_as_uuid(caller_id), role),
                )
            ).one_or_none()
            if paper is None:
                raise ReviewOwnershipError(f"Caller may not access review item {item_uuid}")
            return item, None, None, paper
        attempt = session.get(Attempt, item.attempt_id)
        if attempt is None or attempt.user_id not in visible:
            raise ReviewOwnershipError(f"Caller may not access review item {item_uuid}")
        qr = (
            session.get(QuestionResult, item.question_result_id)
            if item.question_result_id
            else None
        )
        return item, attempt, qr, None

    def _recompute_attempt_totals(
        self, session: Session, attempt: Attempt, results: Sequence[QuestionResult]
    ) -> None:
        """Recompute the attempt's stored total after an override.

        Sums every question's ``effective_marks`` (AI mark, or the teacher's
        override when one is recorded) and re-grades it with the same
        deterministic boundary lookup the original grade used — see module
        docstring. ``results`` is every :class:`QuestionResult` on this
        attempt, passed in (not re-queried) so the caller can share one fetch
        with :meth:`_recompute_weakness_records`.

        **The quiz guard (``docs/quiz-model.md`` §4.5, mandatory).** For
        ``attempt.origin == AttemptOrigin.quiz``, ``grade``/``predicted_grade``/
        ``boundary_source`` are left exactly as the marking path wrote them
        (NULL — a quiz has no grade boundaries, ``AttemptRepository._persist``
        never sets them) and :meth:`_boundaries_for` is never even called.
        Without this guard, the *first* teacher override on any quiz would
        invent a grade the marking path deliberately never wrote — precisely
        the "never invent precision" violation this design spent a column
        avoiding, arriving through the review-override side door.
        ``awarded_marks``/``percentage`` are still recomputed from
        ``effective_marks`` regardless of origin: a quiz mark correction must
        still show up in the student's/teacher's percentage view.
        """
        awarded = sum(qr.effective_marks for qr in results)
        maximum = attempt.maximum_marks
        percentage = round((awarded / maximum) * 100.0, 2) if maximum else 0.0
        attempt.awarded_marks = awarded
        attempt.percentage = percentage
        if attempt.origin != AttemptOrigin.quiz:
            boundaries, boundary_source = self._boundaries_for(attempt)
            grade = grade_for_percentage(percentage, boundaries)
            attempt.grade = grade
            attempt.predicted_grade = grade
            attempt.boundary_source = boundary_source
        session.flush()

    def _recompute_weakness_records(
        self, session: Session, attempt: Attempt, results: Sequence[QuestionResult]
    ) -> None:
        """Recompute this attempt's :class:`WeaknessRecord` rows after an override.

        Re-groups every question's ``effective_marks`` with
        :func:`~lemely.core.analytics.group_weak_areas` — the identical
        topic-bucketing algorithm ``summarize_weaknesses`` used when this
        attempt was first persisted — and diffs the fresh set against what is
        currently stored, keyed by topic (``AttemptRepository.persist_correction``
        never creates two rows for the same topic on one attempt, so a
        topic-keyed diff cannot collide): an existing topic's numbers are
        updated in place, a newly-created loss gets a fresh row, and a topic
        whose lost marks dropped to zero is deleted outright — a restored
        question must not leave behind a stale, zero-loss weakness row (see
        module docstring).
        """
        items = [
            WeakAreaInput(
                question_id=qr.question_id,
                topic=qr.topic,
                awarded_marks=qr.effective_marks,
                maximum_marks=qr.maximum_marks,
            )
            for qr in results
        ]
        fresh_by_topic = {area.topic: area for area in group_weak_areas(items)}

        existing = session.scalars(
            select(WeaknessRecord).where(WeaknessRecord.attempt_id == attempt.id)
        ).all()
        existing_by_topic = {record.topic: record for record in existing}

        for topic, area in fresh_by_topic.items():
            record = existing_by_topic.pop(topic, None)
            if record is None:
                session.add(
                    WeaknessRecord(
                        user_id=attempt.user_id,
                        attempt_id=attempt.id,
                        topic=area.topic,
                        lost_marks=area.lost_marks,
                        maximum_marks=area.maximum_marks,
                        accuracy=area.accuracy,
                        question_ids=list(area.question_ids),
                    )
                )
            else:
                record.lost_marks = area.lost_marks
                record.maximum_marks = area.maximum_marks
                record.accuracy = area.accuracy
                record.question_ids = list(area.question_ids)

        # Any topic no longer net-losing marks (e.g. the override restored it
        # to full marks) is not a weakness at all — same rule
        # summarize_weaknesses/aggregate_weaknesses_from_history apply.
        for stale in existing_by_topic.values():
            session.delete(stale)
        session.flush()

    def _boundaries_for(self, attempt: Attempt) -> tuple[dict[str, float], BoundarySource]:
        """Re-derive the exact boundary map the original grade used.

        Pure function of the exam metadata already on ``attempt`` (subject,
        session, paper) — deterministic, so this returns the identical
        boundaries the marking pipeline resolved at persist time, never a
        second, possibly-different set. Falls back to the global default
        (logged, never raised) if the attempt's metadata cannot round-trip
        through :class:`~lemely.core.schemas.ExamMetadata` — e.g. a
        totals-only attempt written before full metadata was required.
        """
        try:
            metadata = ExamMetadata(
                subject_code=attempt.subject_code or "",
                paper_number=attempt.paper_number or 1,
                paper_variant=attempt.paper_variant or 1,
                session_month=SESSION_MONTH_LABELS.get(attempt.session_month, "Specimen")
                if attempt.session_month is not None
                else "Specimen",
                session_year=attempt.session_year,
            )
            boundaries, source = self._boundaries.resolve(metadata)
            return boundaries, BoundarySource(source)
        except (ValidationError, ValueError) as exc:
            log.warning(
                "review_boundary_resolution_failed", attempt_id=str(attempt.id), error=str(exc)
            )
            return (
                DEFAULT_GRADE_BOUNDARIES,
                attempt.boundary_source or BoundarySource.global_default,
            )


def _to_row(
    item: ReviewQueueItem,
    attempt: Attempt,
    qr: QuestionResult | None,
    class_id: uuid.UUID,
    class_name: str,
    display_name: str,
    *,
    now: datetime,
) -> ReviewQueueRow:
    return ReviewQueueRow(
        item_id=item.id,
        source="student_attempt",
        attempt_id=attempt.id,
        paper_id=None,
        question_result_id=qr.id if qr is not None else None,
        student_id=attempt.user_id,
        student_display_name=display_name,
        class_id=class_id,
        class_name=class_name,
        subject_code=attempt.subject_code,
        paper_number=attempt.paper_number,
        paper_variant=attempt.paper_variant,
        session_month=SESSION_MONTH_LABELS.get(attempt.session_month)
        if attempt.session_month is not None
        else None,
        session_year=attempt.session_year,
        question_id=qr.question_id if qr is not None else None,
        reason=item.reason,
        status=item.status,
        created_at=item.created_at,
        waiting_hours=max((now - item.created_at).total_seconds() / 3600.0, 0.0),
        ai_awarded_marks=qr.awarded_marks if qr is not None else None,
        maximum_marks=qr.maximum_marks if qr is not None else None,
        confidence_score=qr.confidence_score if qr is not None else None,
    )


def _console_report(paper: TeacherPaper) -> AccuracyReport | None:
    """Parse a console paper's stored report, or ``None`` if it has none/unreadable.

    Validating an ``AccuracyReport`` is not free and a single paper commonly
    contributes several queue rows, so :meth:`ReviewService.list_queue` parses
    each paper once and threads the result through rather than letting every
    row re-validate the same JSON.
    """
    if paper.report_json is None:
        return None
    try:
        return AccuracyReport.model_validate(paper.report_json)
    except ValidationError:
        log.warning("console_review_report_unreadable", paper_id=str(paper.id))
        return None


def _console_question(
    report: AccuracyReport | None, question_id: str | None
) -> CorrectedQuestion | None:
    """The flagged question inside a console paper's report, or ``None``.

    ``None`` when the paper has no readable report, when ``question_id`` is
    unset, or when a re-grade produced a report that no longer contains that
    question (the scheme was re-resolved, the scan re-extracted). The queue row
    is still real and still resolvable in that case — it just cannot show marks
    or a confidence it no longer has, and every derived field goes ``None``
    rather than being carried over from a report that has since been replaced.
    """
    if report is None or question_id is None:
        return None
    return next((q for q in report.correction.questions if q.question_id == question_id), None)


def _console_paper_label(paper: TeacherPaper, report: AccuracyReport | None) -> str:
    """The console's own name for a paper — its identity line in the queue.

    Mirrors ``lemely.web.routers.teacher._paper_label`` so a review item and
    the grading-console card for the same scan read identically. Duplicated
    rather than imported because that helper lives in the web layer and takes a
    ``TeacherPaperRow`` snapshot, while this reads the ORM row directly; both
    fall back to the teacher's own filename, never a raw uuid.
    """
    meta = _console_metadata(paper, report)
    if meta is None:
        return paper.original_filename or str(paper.id)
    # `str(...)`, not the field itself: `session_month` is a `Literal`, so
    # appending the year to it in place is an assignment mypy rightly rejects.
    session = str(meta.session_month)
    if meta.session_year is not None:
        session = f"{session} {meta.session_year}"
    return (
        f"Paper {meta.paper_number} V{meta.paper_variant} "
        f"{session} - {paper.created_at.date().isoformat()}"
    )


def _console_metadata(paper: TeacherPaper, report: AccuracyReport | None) -> ExamMetadata | None:
    """The paper's exam identity: its detected metadata, else its report's.

    Detection runs before marking and is cached on the row, so ``metadata_json``
    is the more current of the two; the report's copy is the fallback for a
    paper marked with an attached scheme and no detection pass.
    """
    if paper.metadata_json:
        try:
            return ExamMetadata.model_validate(paper.metadata_json)
        except ValidationError:
            pass
    return report.correction.metadata if report is not None else None


def _to_console_row(
    item: ReviewQueueItem,
    paper: TeacherPaper,
    *,
    now: datetime,
    report: AccuracyReport | None,
) -> ReviewQueueRow:
    """Build a queue row for a console-sourced item (migration ``0034``).

    Every student/class field is ``None``: a console upload has no student
    behind it (D1.12). The paper's label goes in ``student_display_name``,
    which is what T-07 renders as the row's identity — the honest answer to
    "whose work is this" for a scan the teacher marked in bulk.
    """
    question = _console_question(report, item.question_id)
    meta = _console_metadata(paper, report)
    return ReviewQueueRow(
        item_id=item.id,
        source="console_paper",
        attempt_id=None,
        paper_id=paper.id,
        question_result_id=None,
        student_id=None,
        student_display_name=_console_paper_label(paper, report),
        class_id=None,
        class_name=None,
        subject_code=meta.subject_code if meta is not None else None,
        paper_number=meta.paper_number if meta is not None else None,
        paper_variant=meta.paper_variant if meta is not None else None,
        session_month=meta.session_month if meta is not None else None,
        session_year=meta.session_year if meta is not None else None,
        question_id=item.question_id,
        reason=item.reason,
        status=item.status,
        created_at=item.created_at,
        waiting_hours=max((now - item.created_at).total_seconds() / 3600.0, 0.0),
        ai_awarded_marks=question.awarded_marks if question is not None else None,
        maximum_marks=question.maximum_marks if question is not None else None,
        confidence_score=question.confidence_score if question is not None else None,
    )


def _require_attempt(item: ReviewQueueItem, attempt: Attempt | None) -> Attempt:
    """Narrow a non-console item's attempt, or fail loudly.

    ``ck_review_queue_one_source`` (migration ``0034``) guarantees a row with
    no ``teacher_paper_id`` has an ``attempt_id``, and ``_find_any_item``
    already raised for an attempt the caller may not see — so ``None`` here
    means the constraint has been violated in the database. A ``raise``, not
    an ``assert``: ``python -O`` strips asserts, and this is a real invariant
    violation rather than a defensive no-op.
    """
    if attempt is None:
        raise ValueError(f"Review item {item.id} has neither an attempt nor a teacher paper")
    return attempt


def _console_item_detail(
    item: ReviewQueueItem, paper: TeacherPaper, *, now: datetime
) -> ReviewItemDetail:
    """Build T-08's detail for one console item (parses the paper's report once)."""
    """T-08 detail for a console-sourced item.

    The marking evidence — answer, expected answer, topic, feedback, matched
    mark-scheme point ids — all exists on the ``CorrectedQuestion`` inside
    ``teacher_papers.report_json`` and is read straight from it, so a console
    item is as reviewable as an attempt-backed one.

    The **override** fields are the exception, and are always empty: a console
    paper has no ``question_results`` row, which is the only place migration
    ``0005_review_overrides`` gave a teacher's corrected mark to live. That is
    why :meth:`ReviewService.resolve` refuses ``override_marks`` on these items
    rather than accepting a mark it would have to drop.
    """
    report = _console_report(paper)
    question = _console_question(report, item.question_id)
    return ReviewItemDetail(
        row=_to_console_row(item, paper, now=now, report=report),
        student_answer=question.student_answer if question is not None else None,
        expected_answer=question.expected_answer if question is not None else None,
        topic=question.topic if question is not None else None,
        matched_point_ids=list(question.matched_point_ids) if question is not None else [],
        feedback=question.feedback if question is not None else None,
        marker_source=question.marker_source if question is not None else None,
        review_reason=question.review_reason if question is not None else None,
        is_overridden=False,
        teacher_awarded_marks=None,
        teacher_note=None,
        teacher_breakdown=None,
        overridden_by=None,
        overridden_at=None,
        resolution_note=item.resolution_note,
        resolved_by=item.resolved_by,
        resolved_at=item.resolved_at,
    )


def _as_role(value: Role | str) -> Role:
    """Coerce a str/Role to :class:`~lemely.db.models.enums.Role`.

    ``ValueError`` for an unrecognised value, matching :func:`_as_uuid` — a
    role that does not exist must never fall through to a permissive default.
    """
    return value if isinstance(value, Role) else Role(value)


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "BulkApproveResult",
    "BulkApproveSkip",
    "ReviewAlreadyClosedError",
    "ReviewError",
    "ReviewItemDetail",
    "ReviewNotFoundError",
    "ReviewOwnershipError",
    "ReviewQueueRow",
    "ReviewService",
    "ReviewValidationError",
]
