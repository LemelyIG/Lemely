"""Practice-generator endpoints (``/api/student/practice/*``, P4.5).

A new router file, mirroring ``lemely.web.routers.placement`` exactly:
thin, its own DTOs, and no growth of ``student.py``/``teacher.py``.

**Take/resume/save-answer/submit are not here.** They are the existing
``/api/student/quizzes/{assignment_id}`` routes
(``lemely.web.routers.quiz.student_router``), reused verbatim — the same
D4.6 §4 payoff placement already banked. This router only previews,
self-assigns, and exports a practice set for printing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query

from lemely.db.models.enums import QuestionSource, Role
from lemely.db.practice_repo import (
    PracticeCreated,
    PracticeError,
    PracticeExportSet,
    PracticeNotFoundError,
    PracticeOwnershipError,
    PracticePreview,
    PracticeRequest,
    PracticeResultRow,
    PracticeService,
    PracticeTopicsResult,
    PracticeUnavailableError,
)
from lemely.web.deps import AuthContext, get_practice_service, require_role
from lemely.web.schemas_practice import (
    CreatePracticeResponseDTO,
    PracticeExportDTO,
    PracticeExportQuestionDTO,
    PracticePreviewDTO,
    PracticeRequestDTO,
    PracticeResultDTO,
    PracticeResultQuestionDTO,
    PracticeTopicCountDTO,
    PracticeTopicsDTO,
)

if TYPE_CHECKING:
    from lemely.core.difficulty import Band
    from lemely.web.schemas import MarkerSource

router = APIRouter(
    prefix="/api/student/practice", dependencies=[Depends(require_role(Role.student))]
)

_VALID_BANDS: frozenset[str] = frozenset({"foundation", "standard", "challenge"})


def _raise_for(exc: PracticeError) -> NoReturn:
    """Map a :class:`PracticeError` subclass to the matching :class:`HTTPException`."""
    if isinstance(exc, PracticeNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PracticeOwnershipError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc  # pragma: no cover


def _parse_source(source: str | None) -> QuestionSource | None:
    if source is None:
        return None
    try:
        return QuestionSource(source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown source: {source!r}") from exc


def _marker_source(value: str) -> MarkerSource:
    """Narrow :attr:`PracticeResultQuestion.marker_source` onto the wire's `MarkerSource` literal.

    ``PracticeResultQuestion.marker_source`` (``practice_repo.py``) is a plain
    ``str`` — the repo layer sources it from
    ``lemely.db.models.enums.MarkerSource.value`` and does not import the web
    layer's literal type, mirroring how the rest of that module stays free of
    ``lemely.web`` imports. ``PracticeResultQuestionDTO.markerSource`` is typed
    ``MarkerSource`` (``Literal["deterministic", "ai", "missing", "dropped",
    "blank"]``) precisely so the frontend can branch on this value (Important A,
    US-039 final branch review), so a ``str`` reaching it unchecked would defeat
    that one check. This is the one place that narrowing happens — an explicit
    ``if``/``elif`` chain rather than a ``cast``/``# type: ignore``, so mypy
    proves the return really is one of the five literal values and a sixth,
    unexpected one raises instead of silently reaching the wire.

    Checked, not assumed: ``lemely.db.models.enums.MarkerSource`` (the db
    enum ``PracticeResultQuestion.marker_source`` is sourced from, via
    ``.value``) has exactly five members —
    ``deterministic``/``ai``/``missing``/``dropped``/``blank`` — with string
    values identical to this literal's, and ``practice_repo.py``'s sole
    production call site (``_result``) always passes ``qr.marker_source.value``
    where ``qr.marker_source: Mapped[MarkerSource]``. So today the
    ``ValueError`` branch is unreachable in production: it would only fire if a
    future migration added a sixth db-enum member without updating this function
    to match. ``tests/test_web_practice.py`` parametrises this over
    ``MarkerSource`` itself rather than a hand-written list, so adding a member
    without a branch here fails there.
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


def _parse_bands(bands: list[str]) -> tuple[Band, ...]:
    for band in bands:
        if band not in _VALID_BANDS:
            raise HTTPException(status_code=422, detail=f"Unknown difficulty band: {band!r}")
    return tuple(bands)  # type: ignore[arg-type]  # validated against _VALID_BANDS above


def _preview_to_dto(row: PracticePreview) -> PracticePreviewDTO:
    return PracticePreviewDTO(
        available=row.available,
        reason=row.reason,
        requestedCount=row.requested_count,
        availableCount=row.available_count,
        topics=row.topics,
    )


def _created_to_dto(row: PracticeCreated) -> CreatePracticeResponseDTO:
    return CreatePracticeResponseDTO(
        assignmentId=str(row.assignment_id),
        quizId=str(row.quiz_id),
        questionCount=row.question_count,
        requestedCount=row.requested_count,
        topics=row.topics,
        reason=row.reason,
    )


def _export_to_dto(row: PracticeExportSet) -> PracticeExportDTO:
    return PracticeExportDTO(
        assignmentId=str(row.assignment_id),
        quizId=str(row.quiz_id),
        subjectCode=row.subject_code,
        title=row.title,
        questions=[
            PracticeExportQuestionDTO(
                questionRef=q.question_ref,
                position=q.position,
                topic=q.topic,
                difficulty=q.difficulty,
                questionType=q.question_type,
                prompt=q.prompt,
                totalMarks=q.total_marks,
                mcqOptions=q.mcq_options,
            )
            for q in row.questions
        ],
    )


def _result_to_dto(row: PracticeResultRow) -> PracticeResultDTO:
    return PracticeResultDTO(
        assignmentId=str(row.assignment_id),
        quizId=str(row.quiz_id),
        subjectCode=row.subject_code,
        marked=row.marked,
        submissionStatus=row.submission_status,
        awardedMarks=row.awarded_marks,
        maximumMarks=row.maximum_marks,
        questions=[
            PracticeResultQuestionDTO(
                questionRef=q.question_ref,
                position=q.position,
                topic=q.topic,
                totalMarks=q.total_marks,
                awardedMarks=q.awarded_marks,
                confidenceBand=q.confidence_band,
                confidenceScore=q.confidence_score,
                markerSource=_marker_source(q.marker_source),
                needsTeacherReview=q.needs_teacher_review,
            )
            for q in row.questions
        ],
    )


def _topics_to_dto(row: PracticeTopicsResult) -> PracticeTopicsDTO:
    return PracticeTopicsDTO(
        subjectCode=row.subject_code,
        topics=[
            PracticeTopicCountDTO(
                topic=t.topic,
                availableCount=t.available_count,
                syllabusGroup=t.syllabus_group,
                marksLost=t.marks_lost,
            )
            for t in row.topics
        ],
        weakTopics=row.weak_topics,
        untopicedCount=row.untopiced_count,
    )


@router.get("/{subject_code}/preview", response_model=PracticePreviewDTO)
def practice_preview(
    subject_code: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeService, Depends(get_practice_service)],
    count: int = 10,
    topics: Annotated[list[str] | None, Query()] = None,
    weak_topics_only: bool = False,
    difficulty_bands: Annotated[list[str] | None, Query()] = None,
    source: str | None = None,
) -> PracticePreviewDTO:
    """S-20: how many questions this filter set actually matches, right now. No write.

    Query params are snake_case (mirrors ``quiz_pool_count``'s
    ``requested_count``/``target_grade``) — only the JSON body/response DTOs
    are camelCase (see ``schemas_practice.py``).

    ``topics``/``difficulty_bands`` are declared ``Annotated[..., Query()]``
    rather than a bare ``list[str] | None = None`` default — measured against
    this FastAPI/Pydantic version, the bare form silently drops repeated
    query values and always resolves to ``None`` (reproduced with a minimal
    app outside this codebase; ``lemely.web.routers.quiz.quiz_pool_count``'s
    ``topics`` param has the identical, apparently never-exercised, defect).
    """
    request = PracticeRequest(
        subject_code=subject_code,
        count=count,
        topics=tuple(topics or []),
        weak_topics_only=weak_topics_only,
        difficulty_bands=_parse_bands(difficulty_bands or []),
        source=_parse_source(source),
    )
    try:
        result = service.preview(auth.user_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _preview_to_dto(result)


@router.get("/{subject_code}/topics", response_model=PracticeTopicsDTO)
def practice_topics(
    subject_code: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeService, Depends(get_practice_service)],
) -> PracticeTopicsDTO:
    """S-20's topic-selection control: real, servable topics with real counts.

    Filtered through the identical clauses ``GET .../preview`` uses, so an
    offered topic can never be one the pool cannot actually serve. Also
    carries the caller's own weak topics for this subject, so S-20 can
    pre-fill its chips from the server's own vocabulary.
    """
    try:
        result = service.topics(auth.user_id, subject_code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _topics_to_dto(result)


@router.post("", response_model=CreatePracticeResponseDTO, status_code=201)
def create_practice(
    body: PracticeRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeService, Depends(get_practice_service)],
) -> CreatePracticeResponseDTO:
    """Assemble and self-assign a practice set (S-20 -> S-21).

    409, carrying the identical payload ``GET .../preview`` would have
    returned, only when the pool is genuinely empty for this filter set or
    ``weakTopicsOnly`` was requested with no weaknesses recorded yet. A
    filter set that matches *some* but fewer than ``count`` questions still
    succeeds (201) — see ``reason`` on the response (never padded, never
    silently shortened, spec §1.4).
    """
    request = PracticeRequest(
        subject_code=body.subjectCode,
        count=body.count,
        topics=tuple(body.topics),
        weak_topics_only=body.weakTopicsOnly,
        difficulty_bands=_parse_bands(body.difficultyBands),
        source=_parse_source(body.source),
    )
    try:
        result = service.create(auth.user_id, request)
    except PracticeUnavailableError as exc:
        raise HTTPException(
            status_code=409, detail=_preview_to_dto(exc.preview).model_dump()
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _created_to_dto(result)


@router.get("/{assignment_id}/export", response_model=PracticeExportDTO)
def practice_export(
    assignment_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeService, Depends(get_practice_service)],
) -> PracticeExportDTO:
    """S-21: the print/export payload — answer-free by construction (D3.8).

    404 when the assignment does not exist anywhere, or exists but is not a
    ``practice``-kind quiz; 403 when it exists as a practice set but is not
    the caller's — never data.
    """
    try:
        result = service.export(auth.user_id, assignment_id)
    except (PracticeNotFoundError, PracticeOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _export_to_dto(result)


@router.get("/{assignment_id}/result", response_model=PracticeResultDTO)
def practice_result(
    assignment_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeService, Depends(get_practice_service)],
) -> PracticeResultDTO:
    """S-21's poll target: has this practice set been marked, and how did it go.

    404 when the assignment does not exist anywhere, or exists but is not a
    ``practice``-kind quiz; 403 when it exists as a practice set but is not
    the caller's — never data (mirrors :func:`practice_export`'s discipline).
    """
    try:
        result = service.result(auth.user_id, assignment_id)
    except (PracticeNotFoundError, PracticeOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _result_to_dto(result)


__all__ = ["router"]
