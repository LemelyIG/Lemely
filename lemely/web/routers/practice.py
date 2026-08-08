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
    PracticeService,
    PracticeUnavailableError,
)
from lemely.web.deps import AuthContext, get_practice_service, require_role
from lemely.web.schemas_practice import (
    CreatePracticeResponseDTO,
    PracticeExportDTO,
    PracticeExportQuestionDTO,
    PracticePreviewDTO,
    PracticeRequestDTO,
)

if TYPE_CHECKING:
    from lemely.core.difficulty import Band

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


__all__ = ["router"]
