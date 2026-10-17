"""API DTOs for the practice-generator endpoints (``/api/student/practice/*``, P4.5).

Field names are camelCase to match the frontend contract, mirroring
``schemas_placement.py``. Converters live in ``lemely.web.routers.practice``.
"""

from __future__ import annotations

from pydantic import Field

from lemely.web.schemas import ApiModel, MarkerSource


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


class PracticeResultQuestionDTO(ApiModel):
    """One marked question's outcome — feedback on the student's own answer.

    No ``modelAnswer``/``markSchemePoints``/``mcqAnswer`` field exists here
    at all (D3.8's structural-exclusion discipline, mirroring
    ``PracticeExportQuestionDTO``). ``confidenceBand``/``confidenceScore``
    are the marking engine's own confidence for this mark — every displayed
    mark carries its confidence (QUALITY-BAR.md).

    ``markerSource``/``needsTeacherReview`` are the US-039/finding-G signal
    ``QuestionResultDTO`` carries on the quiz wire. A genuine blank
    (``_build_blank_corrected``: ``confidence_band=LOW``,
    ``needs_teacher_review=False``) is indistinguishable from a real
    low-confidence mark by ``confidenceBand`` alone, so the frontend must be
    able to tell "nobody looked at this" apart from "somebody looked and is
    unsure" without re-deriving that rule (see
    ``practiceData.ts::confidenceBandTier``, finding A in the US-039 final
    branch review).

    ``markerSource`` alone now settles it: task #36 gave the blank its own
    ``"blank"`` value (migration ``0040_marker_source_blank``), so it no longer
    shares ``"missing"`` with a *flagged* extraction failure and
    ``needsTeacherReview`` is no longer load-bearing for that distinction.
    ``needsTeacherReview`` stays on the wire because it is its own signal — the
    marker's flag, which ``confidenceTierFor`` reads for questions that WERE
    scored — not as the second half of a twin.
    """

    questionRef: str
    position: int
    topic: str | None
    totalMarks: int
    awardedMarks: int
    confidenceBand: str
    confidenceScore: float
    markerSource: MarkerSource
    needsTeacherReview: bool


class PracticeResultDTO(ApiModel):
    """S-21's result payload: has this practice set been marked, and how did it go.

    ``marked=False`` (with ``awardedMarks``/``maximumMarks`` absent and
    ``questions`` empty) means the submission has not been marked yet —
    never a fabricated zero score. ``submissionStatus`` tells "not
    submitted yet" (``"not_started"``/``"in_progress"``) apart from
    "submitted, being marked" (``"submitted"``).
    """

    assignmentId: str
    quizId: str
    subjectCode: str
    marked: bool
    submissionStatus: str
    awardedMarks: int | None
    maximumMarks: int | None
    questions: list[PracticeResultQuestionDTO]


class PracticeTopicCountDTO(ApiModel):
    """One servable topic, its real unpadded count, and the group it sits under.

    ``syllabusGroup`` exists because the bank **mixes levels**: measured
    live, 0625 returns ``"1 Motion, forces and energy"`` (152) alongside
    ``"1.2 Motion"`` (6) as peers, and the rows are disjoint — picking the
    parent chip does not include the children. S-20 nests by this key rather
    than rendering a flat menu that would quietly mislead.

    ``marksLost`` (Task 8 C3c) is the caller's own net lost marks on this
    topic across every attempt — 0 when there is no recorded loss, and the
    frontend omits the stat entirely rather than rendering "0 marks lost"
    as decoration.
    """

    topic: str
    availableCount: int
    syllabusGroup: str
    marksLost: int


class PracticeTopicsDTO(ApiModel):
    """S-20's topic-selection payload: real, servable topics plus the caller's weak topics.

    ``untopicedCount`` is reported separately from ``topics`` — an
    untopiced row is legitimate practice material, just not a topic.
    """

    subjectCode: str
    topics: list[PracticeTopicCountDTO]
    weakTopics: list[str]
    untopicedCount: int
