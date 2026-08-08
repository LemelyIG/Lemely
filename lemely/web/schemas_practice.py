"""API DTOs for the practice-generator endpoints (``/api/student/practice/*``, P4.5).

Field names are camelCase to match the frontend contract, mirroring
``schemas_placement.py``. Converters live in ``lemely.web.routers.practice``.
"""

from __future__ import annotations

from pydantic import Field

from lemely.web.schemas import ApiModel


class PracticeRequestDTO(ApiModel):
    """Shared body/query shape for a preview or a create (S-20's filter set).

    ``topics`` is ignored when ``weakTopicsOnly`` is ``True`` — the topic
    filter is derived from the caller's own recorded weaknesses instead
    (MISSION §4's acceptance criterion). ``difficultyBands``/``source`` empty
    or omitted means "no filter on that dimension".
    """

    subjectCode: str
    count: int
    topics: list[str] = Field(default_factory=list)
    weakTopicsOnly: bool = False
    difficultyBands: list[str] = Field(default_factory=list)
    source: str | None = None


class PracticePreviewDTO(ApiModel):
    """S-20's live preview: how many questions this filter set actually matches.

    ``available`` is ``True`` whenever creating would succeed at all,
    including the honest-shortfall case (``reason="insufficient_pool"``,
    ``availableCount < requestedCount``) — never padded, never silently
    shortened (spec §1.4).
    """

    available: bool
    reason: str | None
    requestedCount: int
    availableCount: int
    topics: list[str]


class CreatePracticeResponseDTO(ApiModel):
    """201 response for ``POST /api/student/practice``."""

    assignmentId: str
    quizId: str
    questionCount: int
    requestedCount: int
    topics: list[str]
    reason: str | None


class PracticeExportQuestionDTO(ApiModel):
    """One question in the print/export payload — deliberately answer-free.

    No ``modelAnswer``/``markSchemePoints``/``mcqAnswer`` field exists here
    at all (D3.8's structural-exclusion discipline).
    """

    questionRef: str
    position: int
    topic: str | None
    difficulty: str
    questionType: str
    prompt: str
    totalMarks: int
    mcqOptions: list[str] | None


class PracticeExportDTO(ApiModel):
    """S-21's print/export payload."""

    assignmentId: str
    quizId: str
    subjectCode: str
    title: str
    questions: list[PracticeExportQuestionDTO]
