"""Student self-review endpoints (spec 2026-09-17 self-review, "API").

A new router file, mirroring :mod:`lemely.web.routers.student_announcements`:
thin, its own DTOs, no growth of ``student.py``. Every rule lives in
:class:`~lemely.db.self_review_repo.SelfReviewService`; this module only
maps its errors to status codes and its views to DTOs.

Identity is **always** ``auth.user_id``. Cross-student access is a 404 with
a fixed body, never a 403 — matching every other student route, so the
route is not an existence oracle for another student's attempts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.models.enums import Role
from lemely.db.self_review_repo import (
    AttemptQuestion,
    PendingSelfReview,
    PointVerdict,
    RevealedSelfReview,
    SelfReviewAlreadySubmittedError,
    SelfReviewError,
    SelfReviewNotFoundError,
    SelfReviewService,
    SelfReviewValidationError,
)
from lemely.web.deps import AuthContext, get_self_review_service, require_role
from lemely.web.schemas import QuestionResultDTO, student_safe_review_reason
from lemely.web.schemas_student_self_review import (
    SelfReviewPendingDTO,
    SelfReviewPendingPointDTO,
    SelfReviewRevealedDTO,
    SelfReviewRevealedPointDTO,
    SelfReviewSubmissionDTO,
)

if TYPE_CHECKING:
    from lemely.web.schemas import MarkerSource
    from lemely.web.schemas_student_self_review import EvidenceVerdictWire

router = APIRouter(prefix="/api/student/attempts")

_SELF_REVIEW_PATH = "/{attempt_id}/questions/{question_result_id}/self-review"


def _raise_for(exc: SelfReviewError) -> NoReturn:
    """Map a :class:`SelfReviewError` to its status. The 404 body is fixed."""
    if isinstance(exc, SelfReviewNotFoundError):
        raise HTTPException(status_code=404, detail="No such question") from exc
    if isinstance(exc, SelfReviewAlreadySubmittedError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, SelfReviewValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


def _marker_source(value: str) -> MarkerSource:
    """Narrow :attr:`AttemptQuestion.marker_source` onto the wire's `MarkerSource` literal.

    ``AttemptQuestion.marker_source`` (``self_review_repo.py``) is a plain
    ``str`` -- the repo layer sources it from
    ``lemely.db.models.enums.MarkerSource.value`` and does not import the web
    layer's literal type, mirroring
    ``lemely.web.routers.practice._marker_source``, the sibling instance of
    this same defect (US-041 wire-literals fix). ``QuestionResultDTO.markerSource``
    is typed ``MarkerSource`` (``Literal["deterministic", "ai", "missing",
    "dropped", "blank"]``) precisely so the frontend can branch on this value,
    so a ``str`` reaching it unchecked would defeat that one check. An explicit
    ``if``/``elif`` chain, not a ``cast``/``# type: ignore``, so mypy proves the
    return really is one of the five literal values and a sixth, unexpected
    one raises instead of silently reaching the wire.

    Checked, not assumed: ``lemely.db.models.enums.MarkerSource`` has exactly
    five members -- ``deterministic``/``ai``/``missing``/``dropped``/``blank``
    -- with string values identical to this literal's, and
    ``self_review_repo.py``'s sole production call site (``list_questions``)
    always passes ``qr.marker_source.value`` where
    ``qr.marker_source: Mapped[MarkerSource]``. So today the ``ValueError``
    branch is unreachable in production: it would only fire if a future
    migration added a sixth db-enum member without updating this function to
    match.
    """
    if value == "deterministic":
        return "deterministic"
    if value == "ai":
        return "ai"
    if value == "missing":
        return "missing"
    if value == "dropped":
        return "dropped"
    if value == "blank":
        return "blank"
    raise ValueError(f"Unknown marker source: {value!r}")  # pragma: no cover - enum guarantees this


def _evidence_verdict(value: str | None) -> EvidenceVerdictWire | None:
    """Narrow :attr:`RevealedPoint.evidence_verdict` onto the wire's `EvidenceVerdictWire` literal.

    ``RevealedPoint.evidence_verdict`` (``self_review_repo.py``) is a plain
    ``str | None`` -- the repo layer sources it from
    ``lemely.db.models.enums.EvidenceVerdict.value`` (or ``None``) and does
    not import the web layer's literal type.
    ``SelfReviewRevealedPointDTO.evidenceVerdict`` is typed
    ``EvidenceVerdictWire | None`` (``Literal["accepted", "rejected",
    "not_required"] | None``) precisely so the frontend can branch on this
    value, so a ``str`` reaching it unchecked would defeat that one check.
    An explicit ``if``/``elif`` chain, not a ``cast``/``# type: ignore``, so
    mypy proves the return really is one of the three literal values (or
    ``None``) and a fourth, unexpected string raises instead of silently
    reaching the wire.

    Checked, not assumed: ``lemely.db.models.enums.EvidenceVerdict`` has
    exactly three members -- ``accepted``/``rejected``/``not_required`` --
    with string values identical to this literal's, and
    ``self_review_repo.py``'s sole production call site (``_revealed_view``)
    always passes ``p.evidence_verdict.value if p.evidence_verdict else
    None`` where ``p.evidence_verdict: Mapped[EvidenceVerdict | None]``. So
    today the ``ValueError`` branch is unreachable in production: it would
    only fire if a future migration added a fourth db-enum member without
    updating this function to match.
    """
    if value is None:
        return None
    if value == "accepted":
        return "accepted"
    if value == "rejected":
        return "rejected"
    if value == "not_required":
        return "not_required"
    raise ValueError(f"Unknown evidence verdict: {value!r}")  # pragma: no cover


def _pending_dto(view: PendingSelfReview) -> SelfReviewPendingDTO:
    return SelfReviewPendingDTO(
        state=view.state,
        attemptId=str(view.attempt_id),
        questionResultId=str(view.question_result_id),
        questionId=view.question_id,
        maxMarks=view.maximum_marks,
        evidenceRequired=view.evidence_required,
        points=[
            SelfReviewPendingPointDTO(
                markPointId=p.mark_point_id,
                ordinal=p.ordinal,
                markType=p.mark_type,
                tariff=p.tariff,
                pointText=p.point_text,
                isAlternative=p.is_alternative,
                isOptional=p.is_optional,
                groupKey=p.group_key,
                groupMaxMarks=p.group_max_marks,
            )
            for p in view.points
        ],
    )


def _revealed_dto(view: RevealedSelfReview) -> SelfReviewRevealedDTO:
    return SelfReviewRevealedDTO(
        state=view.state,
        attemptId=str(view.attempt_id),
        questionResultId=str(view.question_result_id),
        questionId=view.question_id,
        maxMarks=view.maximum_marks,
        evidenceRequired=view.evidence_required,
        aiMarks=view.ai_marks,
        effectiveMarks=view.effective_marks,
        studentMarks=view.student_marks,
        teacherSettled=view.teacher_settled,
        pendingTeacher=view.pending_teacher,
        submittedAt=view.submitted_at,
        points=[
            SelfReviewRevealedPointDTO(
                markPointId=p.mark_point_id,
                ordinal=p.ordinal,
                markType=p.mark_type,
                tariff=p.tariff,
                pointText=p.point_text,
                isAlternative=p.is_alternative,
                isOptional=p.is_optional,
                groupKey=p.group_key,
                groupMaxMarks=p.group_max_marks,
                awarded=p.awarded,
                studentSelfmark=p.student_selfmark,
                studentEvidence=p.student_evidence,
                evidenceVerdict=_evidence_verdict(p.evidence_verdict),
                markChanged=p.mark_changed,
                absorbedByGroup=p.absorbed_by_group,
                judgeReason=p.judge_reason,
                verdict=p.verdict,
                evidenceSpan=p.evidence_span,
                ecfApplied=p.ecf_applied,
            )
            for p in view.points
        ],
    )


def _question_dto(row: AttemptQuestion) -> QuestionResultDTO:
    """The result screen's row shape, carrying no verdict and no integrity signal.

    Integrity means the two booleans *and* ``review_reason``: the reason is free
    text that ``lemely/io/integrity.py`` appends ``"plagiarism (score 0.94)"``
    to, and ``PaperResult`` renders it verbatim. Suppressing the flags while
    forwarding the sentence would tell the student anyway, with a score on it
    (QUALITY-BAR.md: integrity flags are teacher-only).

    Per-point means ``matched_point_ids``, which is withheld outright.
    ``QuestionResultPoint.awarded`` is ``point.id in matched_point_ids``
    (``lemely/db/question_points.py``), so the list *is* the marker's per-point
    verdict — the very thing the self-review panel asks the student to commit
    against before the reveal. These rows render on the same screen as that
    panel, and this route's ``questionResultId`` is what makes it render, so
    forwarding the ids would leave the answer one Network-tab click away. The
    question's *aggregate* ``awardedMarks`` stays; only per-point ``awarded``
    was ever promised to be withheld.
    """
    return QuestionResultDTO(
        questionId=row.question_id,
        awardedMarks=row.effective_marks,
        maxMarks=row.maximum_marks,
        markerSource=_marker_source(row.marker_source),
        confidence=row.confidence_score,
        feedback=row.feedback,
        matchedPointIds=None,
        reviewReason=student_safe_review_reason(row.review_reason),
        plagiarismFlagged=False,
        topic=row.topic,
        # The marker's frozen flag, forwarded as-is. Distinct from
        # ``pendingTeacher`` below, which is the live queue state, and required
        # on the DTO precisely so a constructor like this one cannot omit it and
        # ship a silently-unflagged page (``QuestionResultDTO.needsTeacherReview``).
        # ``confidenceTierFor`` reads both: without this field a US-039 blank
        # renders "confident" here, because ``pendingTeacher`` is ``False`` for a
        # question that was deliberately never queued.
        needsTeacherReview=row.needs_teacher_review,
        questionResultId=str(row.question_result_id) if row.self_reviewable else None,
        pendingTeacher=row.pending_teacher,
    )


@router.get("/{attempt_id}/questions", response_model=list[QuestionResultDTO])
def list_attempt_questions(
    attempt_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[SelfReviewService, Depends(get_self_review_service)],
) -> list[QuestionResultDTO]:
    """The per-question rows of one of the caller's attempts, for the result screen.

    ``awardedMarks`` is ``effective_marks`` (a self-mark or teacher override
    shows here). ``questionResultId`` is set only where the question has
    point rows, which is exactly where the self-review panel may render.

    A 404 here carries the same fixed ``"No such question"`` body the
    sibling routes use, even though the only cause on this route is the
    attempt. That is deliberate, not a copy-paste: one body for every
    not-yours/not-found case leaves no oracle to enumerate other students'
    attempts with. Do not make it more specific.
    """
    try:
        rows = service.list_questions(auth.user_id, attempt_id)
    except SelfReviewError as exc:
        _raise_for(exc)
    return [_question_dto(row) for row in rows]


@router.get(_SELF_REVIEW_PATH, response_model=SelfReviewPendingDTO | SelfReviewRevealedDTO)
def get_self_review(
    attempt_id: str,
    question_result_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[SelfReviewService, Depends(get_self_review_service)],
) -> SelfReviewPendingDTO | SelfReviewRevealedDTO:
    """The self-review state of one of the caller's questions.

    Before submission the payload is :class:`SelfReviewPendingDTO`, which
    carries no verdict at any depth. After it, :class:`SelfReviewRevealedDTO`.
    """
    try:
        view = service.get(auth.user_id, attempt_id, question_result_id)
    except SelfReviewError as exc:
        _raise_for(exc)
    if isinstance(view, PendingSelfReview):
        return _pending_dto(view)
    return _revealed_dto(view)


@router.post(_SELF_REVIEW_PATH, response_model=SelfReviewRevealedDTO)
def submit_self_review(
    attempt_id: str,
    question_result_id: str,
    payload: SelfReviewSubmissionDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[SelfReviewService, Depends(get_self_review_service)],
) -> SelfReviewRevealedDTO:
    """Record the caller's one self-mark pass and reveal the marker's verdict.

    409 once a pass exists; 422 unless every point carries exactly one verdict.
    """
    try:
        view = service.submit(
            auth.user_id,
            attempt_id,
            question_result_id,
            [
                PointVerdict(mark_point_id=p.markPointId, earned=p.earned, evidence=p.evidence)
                for p in payload.points
            ],
        )
    except SelfReviewError as exc:
        _raise_for(exc)
    return _revealed_dto(view)


__all__ = ["router"]
