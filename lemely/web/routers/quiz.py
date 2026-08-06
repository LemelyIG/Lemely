"""Quiz-builder CRUD endpoints (``/api/teacher/quizzes/*``, P3.5 chunk D).

A new router file rather than extending ``teacher.py`` (already ~1700 LOC
before this chunk) — mirrors ``lemely.web.routers.review``'s precedent: the
quiz builder is its own coherent surface with its own service
(:class:`~lemely.db.quiz_repo.QuizService`) and DTOs, and nothing here needs
anything ``teacher.py`` privately defines. ``teacher.py`` keeps the four
pre-existing ``/quizzes/*`` routes (``pools``/``topics``/``preview``/
``generate`` — the ad hoc AI-quiz-preview feature, unrelated to the
``Quiz``/``QuizQuestion`` model this router owns) at their existing paths;
only ``pools`` and ``generate`` changed in this chunk, per the brief.

Every route is gated to the teacher/school_admin/platform_admin staff triple
(mirroring ``teacher.py``/``review.py``), but row-level ownership inside
:class:`~lemely.db.quiz_repo.QuizService` is stricter than the class/review
services: a quiz belongs to exactly the teacher who built it, with no
school_admin read/administer exception (``docs/quiz-model.md`` names none,
and the brief is explicit: "a teacher may only see and mutate their own
quizzes").
"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.models.enums import QuestionSource, QuizStatus, Role
from lemely.db.quiz_repo import (
    PoolCountResult,
    QuestionGenerationResult,
    QuizDetail,
    QuizError,
    QuizNotFoundError,
    QuizOwnershipError,
    QuizQuestionRow,
    QuizRow,
    QuizService,
    QuizValidationError,
)
from lemely.web.deps import AuthContext, get_quiz_service, require_role
from lemely.web.schemas_quiz import (
    CreateQuizRequestDTO,
    GenerateQuizQuestionsResponseDTO,
    QuizDetailDTO,
    QuizListDTO,
    QuizPoolCountDTO,
    QuizQuestionDTO,
    QuizSummaryDTO,
    SetQuizStatusRequestDTO,
    UpdateQuizDraftRequestDTO,
)

# Mirrors teacher.py's/classes.py's/review.py's staff triple.
_STAFF_ROLES = (Role.teacher, Role.school_admin, Role.platform_admin)

router = APIRouter(
    prefix="/api/teacher/quizzes", dependencies=[Depends(require_role(*_STAFF_ROLES))]
)


# ---------------------------------------------------------------------------
# Error mapping.
# ---------------------------------------------------------------------------


def _raise_for(exc: QuizError) -> NoReturn:
    """Map a :class:`QuizError` subclass to the matching :class:`HTTPException`."""
    if isinstance(exc, QuizNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, QuizOwnershipError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, QuizValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc  # pragma: no cover


def _parse_source(source: str | None) -> QuestionSource | None:
    if source is None:
        return None
    try:
        return QuestionSource(source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown source: {source!r}") from exc


def _parse_status(status: str) -> QuizStatus:
    try:
        return QuizStatus(status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown status: {status!r}") from exc


# ---------------------------------------------------------------------------
# DTO conversion.
# ---------------------------------------------------------------------------


def _quiz_to_dto(row: QuizRow) -> QuizSummaryDTO:
    return QuizSummaryDTO(
        id=str(row.quiz_id),
        subjectCode=row.subject_code,
        title=row.title,
        status=row.status.value,
        targetGrade=row.target_grade,
        includedTopics=list(row.included_topics),
        poolSource=row.pool_source.value if row.pool_source is not None else None,
        requestedCount=row.requested_count,
        timeLimitMinutes=row.time_limit_minutes,
        builderStep=row.builder_step,
        questionCount=row.question_count,
    )


def _question_to_dto(row: QuizQuestionRow) -> QuizQuestionDTO:
    return QuizQuestionDTO(
        id=str(row.id),
        questionBankId=str(row.question_bank_id) if row.question_bank_id is not None else None,
        questionRef=row.question_ref,
        position=row.position,
        status=row.status.value,
        replacedById=str(row.replaced_by_id) if row.replaced_by_id is not None else None,
        topic=row.topic,
        difficulty=row.difficulty,
        questionType=row.question_type,
        prompt=row.prompt,
        modelAnswer=row.model_answer,
        markSchemePoints=list(row.mark_scheme_points),
        mcqOptions=list(row.mcq_options) if row.mcq_options is not None else None,
        mcqAnswer=row.mcq_answer,
        totalMarks=row.total_marks,
    )


def _detail_to_dto(detail: QuizDetail) -> QuizDetailDTO:
    return QuizDetailDTO(
        quiz=_quiz_to_dto(detail.quiz),
        questions=[_question_to_dto(q) for q in detail.questions],
    )


def _generation_to_dto(result: QuestionGenerationResult) -> GenerateQuizQuestionsResponseDTO:
    return GenerateQuizQuestionsResponseDTO(
        created=[_question_to_dto(q) for q in result.created],
        shortfall=dict(result.shortfall) if result.shortfall else None,
    )


def _pool_count_message(
    source: QuestionSource | None, subject_code: str, matching: int
) -> str | None:
    """The exact §2/D3.7 honest-degradation wording, when it applies.

    ``source=past_paper`` matching zero rows for a subject is the genuinely
    empty-bank case D3.7 requires be said in these words, not shown as a
    plausible-looking ``0`` with no explanation.
    """
    if source == QuestionSource.past_paper and matching == 0:
        return f"No past-paper questions indexed for {subject_code} yet; use generated questions."
    return None


def _pool_count_to_dto(
    result: PoolCountResult, *, source: QuestionSource | None, subject_code: str
) -> QuizPoolCountDTO:
    return QuizPoolCountDTO(
        matching=result.matching,
        requested=result.requested,
        byBand=dict(result.by_band),
        shortfall=dict(result.shortfall) if result.shortfall else None,
        difficultyEstimated=result.difficulty_estimated,
        message=_pool_count_message(source, subject_code, result.matching),
    )


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------


@router.post("", response_model=QuizSummaryDTO, status_code=201)
def create_quiz(
    body: CreateQuizRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizSummaryDTO:
    """Create a draft quiz: entering step 1 of the builder (§1.4)."""
    try:
        row = service.create_quiz(auth.user_id, body.subjectCode, body.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _quiz_to_dto(row)


@router.get("", response_model=QuizListDTO)
def list_quizzes(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizListDTO:
    """Every quiz the caller owns, most recently created first."""
    try:
        rows = service.list_quizzes(auth.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return QuizListDTO(quizzes=[_quiz_to_dto(row) for row in rows])


@router.get("/pool-count", response_model=QuizPoolCountDTO)
def quiz_pool_count(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
    subject_code: str,
    requested_count: int = 0,
    target_grade: str | None = None,
    topics: list[str] | None = None,
    source: str | None = None,
) -> QuizPoolCountDTO:
    """T-09 step 4's live pool-count (``docs/quiz-model.md`` §2).

    Registered ahead of ``GET /{quiz_id}`` so ``"pool-count"`` is never
    mistaken for a quiz id.
    """
    source_enum = _parse_source(source)
    try:
        result = service.pool_count(
            auth.user_id,
            subject_code=subject_code,
            target_grade=target_grade,
            requested_count=requested_count,
            topics=topics,
            source=source_enum,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _pool_count_to_dto(result, source=source_enum, subject_code=subject_code)


@router.get("/{quiz_id}", response_model=QuizDetailDTO)
def get_quiz(
    quiz_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizDetailDTO:
    """One owned quiz plus every materialized question row (§1.5).

    An out-of-scope quiz is a 403; an id that maps to no quiz anywhere is a
    404 — the same split every other owner-scoped route in this codebase
    uses (see ``ClassService``'s docstring for the accepted 403-vs-404
    existence-oracle trade-off).
    """
    try:
        detail = service.get_quiz(auth.user_id, quiz_id)
    except (QuizNotFoundError, QuizOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _detail_to_dto(detail)


@router.patch("/{quiz_id}", response_model=QuizSummaryDTO)
def patch_quiz_draft(
    quiz_id: str,
    body: UpdateQuizDraftRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizSummaryDTO:
    """Partial-update a draft quiz's step-2/3/4 fields.

    A non-draft quiz (409-shaped as 422 — the mutation is invalid for this
    resource's state, not a conflicting concurrent write) rejects the whole
    patch: §1.4 forbids editing a live quiz under students mid-attempt.
    """
    pool_source = _parse_source(body.poolSource)
    try:
        row = service.patch_draft(
            auth.user_id,
            quiz_id,
            title=body.title,
            target_grade=body.targetGrade,
            included_topics=body.includedTopics,
            pool_source=pool_source,
            requested_count=body.requestedCount,
            time_limit_minutes=body.timeLimitMinutes,
            builder_step=body.builderStep,
        )
    except (QuizNotFoundError, QuizOwnershipError, QuizValidationError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _quiz_to_dto(row)


@router.post("/{quiz_id}/status", response_model=QuizSummaryDTO)
def set_quiz_status(
    quiz_id: str,
    body: SetQuizStatusRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizSummaryDTO:
    """Transition a quiz's status. Never backwards (§1.4)."""
    new_status = _parse_status(body.status)
    try:
        row = service.set_status(auth.user_id, quiz_id, new_status)
    except (QuizNotFoundError, QuizOwnershipError, QuizValidationError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _quiz_to_dto(row)


@router.post(
    "/{quiz_id}/questions/generate",
    response_model=GenerateQuizQuestionsResponseDTO,
)
def generate_quiz_questions(
    quiz_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> GenerateQuizQuestionsResponseDTO:
    """Materialize the quiz's question set from the bank (§1.5/§3).

    Additive: calling again after raising ``requestedCount`` tops the set
    up rather than replacing it (see ``QuizService.generate_questions``).
    """
    try:
        result = service.generate_questions(auth.user_id, quiz_id)
    except (QuizNotFoundError, QuizOwnershipError, QuizValidationError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _generation_to_dto(result)


@router.delete("/{quiz_id}/questions/{question_ref}", response_model=QuizSummaryDTO)
def remove_quiz_question(
    quiz_id: str,
    question_ref: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizSummaryDTO:
    """Curate a question out of a draft. Kept (``status=removed``), not deleted.

    Returns the refreshed quiz summary (its ``questionCount`` reflects the
    removal) rather than the removed row itself — the caller already has
    the row it just asked to remove.
    """
    try:
        service.remove_question(auth.user_id, quiz_id, question_ref)
        row = service.get_quiz(auth.user_id, quiz_id).quiz
    except (QuizNotFoundError, QuizOwnershipError, QuizValidationError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _quiz_to_dto(row)


__all__ = ["router"]
