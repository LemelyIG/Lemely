"""API DTOs for the placement-test endpoints (``/api/student/placement/*``, P4.4 chunk B-4, D4.6).

Field names are camelCase to match the frontend contract, mirroring
``schemas_quiz.py``. Converters live in ``lemely.web.routers.placement``.
"""

from __future__ import annotations

from lemely.web.schemas import ApiModel


class PlacementAvailabilityDTO(ApiModel):
    """S-03's payload: whether a placement test can be assembled, and why not.

    ``reason`` is a machine-readable
    :class:`~lemely.core.placement.UnavailableReason` value (e.g.
    ``"no_questions"``), or ``None`` when ``available`` is ``True`` — S-03
    says something specific per subject rather than fail generically.
    """

    available: bool
    reason: str | None
    questionCount: int
    topicCount: int
    estimatedMinutes: float


class CreatePlacementRequestDTO(ApiModel):
    subjectCode: str


class CreatePlacementResponseDTO(ApiModel):
    """201 response for ``POST /api/student/placement``."""

    assignmentId: str
    quizId: str
    questionCount: int
    topicCount: int
    estimatedMinutes: float


class PlacementQuestionResultDTO(ApiModel):
    questionRef: str
    topic: str | None
    awardedMarks: int
    maximumMarks: int


class PlacementTopicBreakdownDTO(ApiModel):
    topic: str
    lostMarks: int
    maximumMarks: int
    accuracy: float


class PlacementResultDTO(ApiModel):
    """S-05's payload: not a grade — a starting picture.

    ``marked=False`` (with every list/count field empty) means the
    submission has not been marked yet — S-05 must say so, not render a
    half result. ``spansMultipleBands`` gates whether S-05 may show a
    working-level estimate at all (D4.6 §5); when it is ``False`` the
    sample was too narrow, and S-05 shows strongest/weakest topics only.
    """

    assignmentId: str
    quizId: str
    subjectCode: str
    marked: bool
    awardedMarks: int | None
    maximumMarks: int | None
    questions: list[PlacementQuestionResultDTO]
    topicBreakdown: list[PlacementTopicBreakdownDTO]
    spansMultipleBands: bool
