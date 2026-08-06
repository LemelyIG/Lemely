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

import threading
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException

from lemely.db.class_repo import ClassNotFoundError, ClassOwnershipError
from lemely.db.models.enums import QuestionSource, QuizStatus, Role
from lemely.db.quiz_marking_repo import QuizMarkingError, QuizMarkingService
from lemely.db.quiz_repo import (
    PoolCountResult,
    QuestionGenerationResult,
    QuizAssignmentRow,
    QuizDetail,
    QuizError,
    QuizNotFoundError,
    QuizOwnershipError,
    QuizQuestionRow,
    QuizRow,
    QuizService,
    QuizValidationError,
)
from lemely.db.quiz_taking_repo import (
    AssignedQuizRow,
    QuizAnswerRow,
    QuizTakeDetail,
    QuizTakingError,
    QuizTakingNotFoundError,
    QuizTakingOwnershipError,
    QuizTakingService,
    QuizTakingValidationError,
    SubmitResultRow,
)
from lemely.web.deps import (
    AuthContext,
    get_quiz_marking_service,
    get_quiz_service,
    get_quiz_taking_service,
    require_role,
)
from lemely.web.schemas_quiz import (
    CreateQuizAssignmentRequestDTO,
    CreateQuizRequestDTO,
    GenerateQuizQuestionsResponseDTO,
    QuizAssignmentDTO,
    QuizAssignmentListDTO,
    QuizDetailDTO,
    QuizListDTO,
    QuizPoolCountDTO,
    QuizQuestionDTO,
    QuizSummaryDTO,
    SaveAnswerRequestDTO,
    SaveAnswerResponseDTO,
    SetQuizStatusRequestDTO,
    StudentQuizHeaderDTO,
    StudentQuizListDTO,
    StudentQuizListItemDTO,
    StudentQuizQuestionDTO,
    StudentQuizTakeDTO,
    SubmitQuizResponseDTO,
    UpdateQuizDraftRequestDTO,
)

if TYPE_CHECKING:
    import uuid

log = structlog.get_logger(__name__)

# Mirrors teacher.py's/classes.py's/review.py's staff triple.
_STAFF_ROLES = (Role.teacher, Role.school_admin, Role.platform_admin)

router = APIRouter(
    prefix="/api/teacher/quizzes", dependencies=[Depends(require_role(*_STAFF_ROLES))]
)

#: Student-side quiz-taking routes (S-26). A second router, not a second
#: prefix under ``router``: the role gate differs (student vs the staff
#: triple), so the two cannot share one ``APIRouter`` without every route
#: re-declaring its own ``dependencies=``. Registered alongside ``router`` in
#: ``lemely.web.app`` (P3.5 chunk E brief: keeping quiz code in one file beats
#: growing ``student.py``, already ~950 LOC before this chunk).
student_router = APIRouter(
    prefix="/api/student/quizzes", dependencies=[Depends(require_role(Role.student))]
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


def _raise_for_class(exc: ClassNotFoundError | ClassOwnershipError) -> NoReturn:
    """Map a class-scope failure to the matching :class:`HTTPException`.

    Propagated unchanged from :meth:`~lemely.db.quiz_repo.QuizService.create_assignment`/
    ``list_assignments`` — the same 404/403 split ``lemely.web.routers.classes``
    already uses for these exact exceptions.
    """
    if isinstance(exc, ClassNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise HTTPException(status_code=403, detail=str(exc)) from exc


def _raise_for_taking(exc: QuizTakingError) -> NoReturn:
    """Map a :class:`QuizTakingError` subclass to the matching :class:`HTTPException`."""
    if isinstance(exc, QuizTakingNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, QuizTakingOwnershipError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, QuizTakingValidationError):
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


def _parse_datetime(value: str | None, *, field: str) -> datetime | None:
    """Parse an optional ISO-8601 datetime request field. Must be tz-aware.

    Mirrors ``lemely.web.routers.teacher._parse_recorded_at``'s defensive
    parse, but raises a 422 on failure (a request-body validation error)
    rather than silently returning ``None`` (that convention is for
    defensively reading already-persisted, trusted data).
    """
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"{field} must be timezone-aware: {value!r}")
    return parsed


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


def _assignment_to_dto(row: QuizAssignmentRow) -> QuizAssignmentDTO:
    return QuizAssignmentDTO(
        id=str(row.assignment_id),
        classId=str(row.class_id),
        className=row.class_name,
        assignedAt=row.assigned_at.isoformat(),
        dueAt=row.due_at.isoformat() if row.due_at is not None else None,
        closesAt=row.closes_at.isoformat() if row.closes_at is not None else None,
        rosterSize=row.roster_size,
        submissionCounts=dict(row.submission_counts),
    )


def _student_quiz_to_dto(row: AssignedQuizRow) -> StudentQuizListItemDTO:
    return StudentQuizListItemDTO(
        assignmentId=str(row.assignment_id),
        quizTitle=row.quiz_title,
        subjectCode=row.subject_code,
        className=row.class_name,
        teacherName=row.teacher_name,
        assignedAt=row.assigned_at.isoformat(),
        dueAt=row.due_at.isoformat() if row.due_at is not None else None,
        closesAt=row.closes_at.isoformat() if row.closes_at is not None else None,
        questionCount=row.question_count,
        timeLimitMinutes=row.time_limit_minutes,
        submissionStatus=row.submission_status.value,
        isOpen=row.is_open,
        isOverdue=row.is_overdue,
    )


def _take_to_dto(detail: QuizTakeDetail) -> StudentQuizTakeDTO:
    header = detail.header
    return StudentQuizTakeDTO(
        header=StudentQuizHeaderDTO(
            quizTitle=header.quiz_title,
            subjectCode=header.subject_code,
            className=header.class_name,
            teacherName=header.teacher_name,
            dueAt=header.due_at.isoformat() if header.due_at is not None else None,
            closesAt=header.closes_at.isoformat() if header.closes_at is not None else None,
            timeLimitMinutes=header.time_limit_minutes,
            submissionStatus=header.submission_status.value,
            isOpen=header.is_open,
            isOverdue=header.is_overdue,
            unansweredCount=header.unanswered_count,
        ),
        questions=[
            StudentQuizQuestionDTO(
                id=str(q.id),
                questionRef=q.question_ref,
                position=q.position,
                topic=q.topic,
                difficulty=q.difficulty,
                questionType=q.question_type,
                prompt=q.prompt,
                totalMarks=q.total_marks,
                mcqOptions=list(q.mcq_options) if q.mcq_options is not None else None,
                answerText=q.answer_text,
                workingText=q.working_text,
                answeredAt=q.answered_at.isoformat() if q.answered_at is not None else None,
            )
            for q in detail.questions
        ],
    )


def _answer_to_dto(row: QuizAnswerRow) -> SaveAnswerResponseDTO:
    return SaveAnswerResponseDTO(
        questionRef=row.question_ref,
        answerText=row.answer_text,
        workingText=row.working_text,
        answeredAt=row.answered_at.isoformat() if row.answered_at is not None else None,
    )


def _submit_to_dto(row: SubmitResultRow) -> SubmitQuizResponseDTO:
    return SubmitQuizResponseDTO(
        submissionStatus=row.submission_status.value,
        answeredCount=row.answered_count,
        unansweredCount=row.unanswered_count,
    )


def _trigger_marking_in_background(
    marking_service: QuizMarkingService, submission_id: uuid.UUID
) -> None:
    """Kick off ``QuizMarkingService.mark_submission`` on a background thread.

    Mirrors the ``def run(): ...`` + daemon-thread shape
    ``lemely.web.sse.bus_event_stream``/``lemely.web.routers.student.student_correct``
    use for the self-mark pipeline (``docs/quiz-model.md`` §4.2: "a synchronous
    mark would put a multi-question Gemini round trip inside an HTTP
    request"). Unlike that SSE case, the submit response is a plain JSON body
    that must not block on marking at all, so this thread is fire-and-forget
    — the caller (:func:`submit_student_quiz`) returns immediately after
    starting it.

    ``mark_submission`` already catches and records its own marking failures
    (``quiz_submissions.marking_error``, see ``lemely.db.quiz_marking_repo``'s
    module docstring); the ``except`` clauses here are a last-resort net for
    state races (``QuizMarkingError``) or a genuine bug, so a daemon thread
    never fails silently with only a bare stderr traceback.
    """

    def run() -> None:
        try:
            marking_service.mark_submission(submission_id)
        except QuizMarkingError as exc:
            log.warning(
                "quiz_marking_trigger_rejected",
                submission_id=str(submission_id),
                error=str(exc),
            )
        except Exception:
            log.exception("quiz_marking_trigger_unexpected_error", submission_id=str(submission_id))

    threading.Thread(target=run, daemon=True).start()


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


# ---------------------------------------------------------------------------
# Assignments (§1.6, P3.5 chunk E) — teacher side.
# ---------------------------------------------------------------------------


@router.post("/{quiz_id}/assignments", response_model=QuizAssignmentDTO, status_code=201)
def create_quiz_assignment(
    quiz_id: str,
    body: CreateQuizAssignmentRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizAssignmentDTO:
    """Assign an owned quiz to a class. A ``draft`` quiz becomes ``assigned``.

    Class scope is checked via ``ClassService.get_class`` and propagated
    unchanged (404/403) — never re-derived here. 422 covers: the quiz has no
    ``included`` question, is ``closed``/``archived``, is already assigned to
    this class, or ``closesAt`` is earlier than ``dueAt``.
    """
    due_at = _parse_datetime(body.dueAt, field="dueAt")
    closes_at = _parse_datetime(body.closesAt, field="closesAt")
    try:
        row = service.create_assignment(
            auth.user_id,
            auth.role,
            quiz_id,
            body.classId,
            due_at=due_at,
            closes_at=closes_at,
        )
    except (QuizNotFoundError, QuizOwnershipError, QuizValidationError) as exc:
        _raise_for(exc)
    except (ClassNotFoundError, ClassOwnershipError) as exc:
        _raise_for_class(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _assignment_to_dto(row)


@router.get("/{quiz_id}/assignments", response_model=QuizAssignmentListDTO)
def list_quiz_assignments(
    quiz_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizAssignmentListDTO:
    """Every assignment of an owned quiz, with live roster size and submission counts.

    Counts only (§1.6/chunk-E brief) — no marks, no averages, no per-student
    results. T-10's results aggregation is chunk F.
    """
    try:
        rows = service.list_assignments(auth.user_id, auth.role, quiz_id)
    except (QuizNotFoundError, QuizOwnershipError) as exc:
        _raise_for(exc)
    except (ClassNotFoundError, ClassOwnershipError) as exc:
        _raise_for_class(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return QuizAssignmentListDTO(assignments=[_assignment_to_dto(row) for row in rows])


@router.delete("/{quiz_id}/assignments/{assignment_id}", status_code=204)
def delete_quiz_assignment(
    quiz_id: str,
    assignment_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> None:
    """Unassign a quiz from a class. Refused (422) once any student has started.

    ``quiz_submissions`` cascades from ``quiz_assignments`` — unassigning
    once a submission exists beyond ``not_started`` would silently destroy
    that student's work.
    """
    try:
        service.delete_assignment(auth.user_id, quiz_id, assignment_id)
    except (QuizNotFoundError, QuizOwnershipError, QuizValidationError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Student quiz-taking (S-26, P3.5 chunk E).
# ---------------------------------------------------------------------------


@student_router.get("", response_model=StudentQuizListDTO)
def list_student_quizzes(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[QuizTakingService, Depends(get_quiz_taking_service)],
) -> StudentQuizListDTO:
    """Assignments for classes the caller is enrolled in (``assigned``/``closed`` quizzes only)."""
    rows = service.list_assigned(auth.user_id)
    return StudentQuizListDTO(quizzes=[_student_quiz_to_dto(row) for row in rows])


@student_router.get("/{assignment_id}", response_model=StudentQuizTakeDTO)
def get_student_quiz(
    assignment_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[QuizTakingService, Depends(get_quiz_taking_service)],
) -> StudentQuizTakeDTO:
    """The take payload (S-26): header + every ``included`` question, in order.

    Lazily creates the ``quiz_submissions`` row on first open, only when the
    quiz is not closed (§1.7). Never carries ``modelAnswer``,
    ``markSchemePoints``, or ``mcqAnswer`` — see ``StudentQuizQuestionDTO``.
    """
    try:
        detail = service.get_take(auth.user_id, assignment_id)
    except (QuizTakingNotFoundError, QuizTakingOwnershipError) as exc:
        _raise_for_taking(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _take_to_dto(detail)


@student_router.put("/{assignment_id}/answers/{question_ref}", response_model=SaveAnswerResponseDTO)
def save_student_quiz_answer(
    assignment_id: str,
    question_ref: str,
    body: SaveAnswerRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[QuizTakingService, Depends(get_quiz_taking_service)],
) -> SaveAnswerResponseDTO:
    """Auto-save one answer, upserted on ``(submission, question_ref)``.

    Creates the submission row if the student saves without a prior GET.
    422 when the quiz is closed, the submission is already
    submitted/marked, or ``question_ref`` is not an included question.
    """
    try:
        row = service.save_answer(
            auth.user_id,
            assignment_id,
            question_ref,
            answer_text=body.answerText,
            working_text=body.workingText,
        )
    except (QuizTakingNotFoundError, QuizTakingOwnershipError, QuizTakingValidationError) as exc:
        _raise_for_taking(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _answer_to_dto(row)


@student_router.post("/{assignment_id}/submit", response_model=SubmitQuizResponseDTO)
def submit_student_quiz(
    assignment_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[QuizTakingService, Depends(get_quiz_taking_service)],
    marking_service: Annotated[QuizMarkingService, Depends(get_quiz_marking_service)],
) -> SubmitQuizResponseDTO:
    """Submit: ``status=submitted``, then trigger marking in the background.

    The response returns as soon as the submission is recorded —
    ``submissionStatus`` is always ``"submitted"`` here, never ``"marked"``.
    Marking (``QuizMarkingService.mark_submission``, P3.5 chunk F1) runs on a
    background thread so a multi-question Gemini round trip never sits inside
    this request (``docs/quiz-model.md`` §4.2); the student sees "being
    marked" until a later read observes ``marked``.
    """
    try:
        result = service.submit(auth.user_id, assignment_id)
    except (QuizTakingNotFoundError, QuizTakingOwnershipError, QuizTakingValidationError) as exc:
        _raise_for_taking(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _trigger_marking_in_background(marking_service, result.submission_id)
    return _submit_to_dto(result)


__all__ = ["router", "student_router"]
