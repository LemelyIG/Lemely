"""Review queue + override service — T-07/T-08 backend (P3.4).

Mirrors :mod:`lemely.db.class_repo`'s shape: pure ownership/mutation logic
over a ``sessionmaker``, domain errors mapped to HTTP status codes by a thin
router layer (:mod:`lemely.web.routers.review`), testable against Postgres
with no GoTrue dependency.

**Tenancy** is the union of every roster the caller may see — the identical
rule :func:`lemely.web.routers.teacher._visible_students` already enforces
for every other student-scoped teacher route (D3.1). :class:`ReviewService`
does not import that function (it lives in the web layer); instead it composes
the same two :class:`~lemely.db.class_repo.ClassService` calls
(``list_classes`` + ``roster``) that function does, so the two call sites can
never define "visible student" differently. A review-queue item whose attempt
belongs to a student outside that union is a :class:`ReviewOwnershipError`
(403) carrying no data, exactly like :class:`~lemely.db.class_repo.ClassOwnershipError`.

**No new table.** ``review_queue`` (0002) already carries reason / status /
assignment / resolution; the only new persistent state P3.4 needed is *what
the teacher changed the mark to*, which belongs on the
:class:`~lemely.db.models.attempts.QuestionResult` it corrects (migration
``0005_review_overrides``) — a question can accumulate more than one
review-queue row (e.g. a ``low_confidence`` row and a ``plagiarism_flag`` row
for the same question, see ``AttemptRepository.persist_correction``), but it
has exactly one AI mark and at most one teacher correction.

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

from lemely.core.analytics import DEFAULT_GRADE_BOUNDARIES, grade_for_percentage
from lemely.core.schemas import ExamMetadata
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import SESSION_MONTH_LABELS, BoundarySource, ReviewReason, ReviewStatus
from lemely.db.models.ops import ReviewQueueItem
from lemely.io.grade_boundaries import GradeBoundaryStore

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.class_repo import ClassService
    from lemely.db.models.enums import Role

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
    """One review-queue entry, enriched with the display context T-07 needs."""

    item_id: uuid.UUID
    attempt_id: uuid.UUID
    question_result_id: uuid.UUID | None
    student_id: uuid.UUID
    student_display_name: str
    class_id: uuid.UUID
    class_name: str
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
        if not visible:
            return []
        reason_enum: ReviewReason | None = None
        if reason is not None:
            try:
                reason_enum = ReviewReason(reason)
            except ValueError:
                return []
        with self._sessionmaker() as session:
            stmt = (
                select(ReviewQueueItem, Attempt, QuestionResult)
                .join(Attempt, ReviewQueueItem.attempt_id == Attempt.id)
                .outerjoin(QuestionResult, ReviewQueueItem.question_result_id == QuestionResult.id)
                .where(
                    ReviewQueueItem.status == ReviewStatus.open,
                    Attempt.user_id.in_(visible.keys()),
                )
                .order_by(ReviewQueueItem.created_at)
            )
            if reason_enum is not None:
                stmt = stmt.where(ReviewQueueItem.reason == reason_enum)
            rows = session.execute(stmt).all()
        now = datetime.now(UTC)
        results: list[ReviewQueueRow] = []
        for item, attempt, qr in rows:
            class_id_, class_name, display_name = visible[attempt.user_id]
            out = _to_row(item, attempt, qr, class_id_, class_name, display_name, now=now)
            if min_age_hours is not None and out.waiting_hours < min_age_hours:
                continue
            results.append(out)
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
            item, attempt, qr = self._find_item(session, item_id, visible)
            class_id_, class_name, display_name = visible[attempt.user_id]
            now = datetime.now(UTC)
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
        (see module docstring), labelling the mark as a teacher correction and
        attributing who/when.

        Raises:
            ReviewNotFoundError: No item exists with ``item_id`` (404).
            ReviewOwnershipError: The caller may not access this item (403).
            ReviewAlreadyClosedError: The item is not ``open`` (409).
            ReviewValidationError: ``override_marks`` was supplied but the item
                has no underlying question result, or the value is out of
                range (422).
        """
        caller_uuid = _as_uuid(caller_id)
        visible = self._visible_class_map(caller_id, caller_role)
        with self._sessionmaker() as session, session.begin():
            item, attempt, qr = self._find_item(session, item_id, visible)
            if item.status != ReviewStatus.open:
                raise ReviewAlreadyClosedError(
                    f"Review item {item.id} is already {item.status.value}"
                )
            now = datetime.now(UTC)
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
                self._recompute_attempt_totals(session, attempt)
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
            item, attempt, qr = self._find_item(session, item_id, visible)
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
                item = session.get(ReviewQueueItem, item_uuid)
                if item is None:
                    skipped.append(BulkApproveSkip(item_id=item_uuid, reason="not_found"))
                    continue
                attempt = session.get(Attempt, item.attempt_id)
                if attempt is None or attempt.user_id not in visible:
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

    def _find_item(
        self,
        session: Session,
        item_id: uuid.UUID | str,
        visible: dict[uuid.UUID, tuple[uuid.UUID, str, str]],
    ) -> tuple[ReviewQueueItem, Attempt, QuestionResult | None]:
        item_uuid = _as_uuid(item_id)
        item = session.get(ReviewQueueItem, item_uuid)
        if item is None:
            raise ReviewNotFoundError(f"Unknown review item: {item_uuid}")
        attempt = session.get(Attempt, item.attempt_id)
        if attempt is None or attempt.user_id not in visible:
            raise ReviewOwnershipError(f"Caller may not access review item {item_uuid}")
        qr = (
            session.get(QuestionResult, item.question_result_id)
            if item.question_result_id
            else None
        )
        return item, attempt, qr

    def _recompute_attempt_totals(self, session: Session, attempt: Attempt) -> None:
        """Recompute the attempt's stored total after an override.

        Sums every question's ``effective_marks`` (AI mark, or the teacher's
        override when one is recorded) and re-grades it with the same
        deterministic boundary lookup the original grade used — see module
        docstring.
        """
        results = session.scalars(
            select(QuestionResult).where(QuestionResult.attempt_id == attempt.id)
        ).all()
        awarded = sum(qr.effective_marks for qr in results)
        maximum = attempt.maximum_marks
        percentage = round((awarded / maximum) * 100.0, 2) if maximum else 0.0
        boundaries, boundary_source = self._boundaries_for(attempt)
        grade = grade_for_percentage(percentage, boundaries)
        attempt.awarded_marks = awarded
        attempt.percentage = percentage
        attempt.grade = grade
        attempt.predicted_grade = grade
        attempt.boundary_source = boundary_source
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
        attempt_id=attempt.id,
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
