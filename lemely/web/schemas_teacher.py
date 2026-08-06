"""Teacher-portal API DTOs (camelCase wire format).

These models mirror the frontend teacher-portal contract in
``web/src/portals/teacher/data.ts`` and ``screens/*``. They live apart from
``lemely.web.schemas`` (which holds the portal-agnostic grading DTOs) so the
teacher wire format can evolve without disturbing the shared converters.

**Data provenance.** Every field on these DTOs is documented as either
*data-backed* (computed from a :class:`CorrectionResult`, the
:class:`HistoryStore`, parsed mark schemes, or the analytics helpers) or
*structurally-empty* (a shape the mock renders that has no backend source yet —
attendance, retention minutes, hand-written narratives). Structurally-empty
collections default to empty and structurally-empty scalars to typed-neutral
values; none of the mock's demo numbers are hard-coded.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lemely.web.schemas import ApiModel, QuestionResultDTO, WeakAreaDTO

PaperKind = Literal["graded", "review", "processing", "queued"]
SchemeStatus = Literal["parsed", "pending", "custom"]


class StatCardDTO(ApiModel):
    """A single overview / class summary stat card.

    All fields are data-backed: ``value``/``unit``/``foot`` are rendered from
    real aggregates. ``valueTone``/``footTone`` are presentation hints the
    backend chooses from computed thresholds, never from the mock.
    """

    key: str
    value: str
    unit: str | None = None
    foot: str | None = None
    valueTone: Literal["t1", "accent", "err"] = "t1"
    footTone: Literal["t2", "ok", "err"] = "t2"


class DetectedFieldDTO(ApiModel):
    """One detected-metadata row for the grading console (all data-backed)."""

    key: str
    value: str


class UploadResponseDTO(ApiModel):
    """Response for ``POST /api/papers/upload``.

    Data-backed: ``jobId`` (registry id), ``paperId``, and ``detected`` (from
    :func:`ScanMetadataExtractor` over the scan, or empty when detection is
    skipped/unavailable).
    """

    jobId: str
    paperId: str
    detected: list[DetectedFieldDTO] = Field(default_factory=list)


class PipelineStepDTO(ApiModel):
    """A grading-pipeline progress step.

    Data-backed: ``label`` and ``count`` reflect the real per-stage counts
    derived from the grading run; ``state`` is computed from those counts.
    """

    label: str
    count: str
    state: Literal["done", "active", "idle"]


class BatchTabDTO(ApiModel):
    """A grading batch filter tab with a live count (data-backed)."""

    id: Literal["all", "review", "graded", "processing"]
    label: str
    count: str


class PaperSummaryDTO(ApiModel):
    """One paper card in the grading grid.

    Data-backed: ``id``, ``name`` (student id), ``kind``/``status``,
    ``awardedMarks``/``maxMarks``, ``confidence``, ``needsReview``. ``pageCount``
    is *structurally-empty* (``None``) unless the pipeline recorded it — the mock's
    "12 pg" has no backend source.
    """

    id: str
    name: str
    kind: PaperKind
    status: str
    awardedMarks: int | None = None
    maxMarks: int | None = None
    confidence: float | None = None
    needsReview: bool = False
    pageCount: int | None = None


class PaperListDTO(ApiModel):
    """Response for ``GET /api/papers`` — the batch grid plus its tabs."""

    papers: list[PaperSummaryDTO] = Field(default_factory=list)
    tabs: list[BatchTabDTO] = Field(default_factory=list)


class PaperDetailDTO(ApiModel):
    """Response for ``GET /api/papers/{id}``.

    Data-backed: ``metadata`` (detected fields), ``pipeline`` steps, and the full
    per-question ``questions`` list plus ``weakAreas`` from the stored
    :class:`CorrectionResult`.
    """

    id: str
    name: str
    kind: PaperKind
    awardedMarks: int
    maxMarks: int
    needsReview: bool
    metadata: list[DetectedFieldDTO] = Field(default_factory=list)
    pipeline: list[PipelineStepDTO] = Field(default_factory=list)
    questions: list[QuestionResultDTO] = Field(default_factory=list)
    weakAreas: list[WeakAreaDTO] = Field(default_factory=list)


class QueueRowDTO(ApiModel):
    """A low-confidence flagged item in the review queue.

    Data-backed from stored corrections: ``paperId``, ``name`` (student id),
    ``questionId``, ``topic``, ``confidence``, ``awardedMarks``/``maxMarks``.
    """

    paperId: str
    name: str
    questionId: str
    topic: str | None = None
    confidence: float | None = None
    awardedMarks: int
    maxMarks: int


class GradingQueueDTO(ApiModel):
    """Response for ``GET /api/grading/queue``."""

    rows: list[QueueRowDTO] = Field(default_factory=list)


class SchemeRowDTO(ApiModel):
    """A parsed / pending / custom mark-scheme row.

    Data-backed: ``doc`` (filename), ``paper``, ``session``, ``maxMarks``,
    ``questionCount``, ``status``. All derived from the parsed
    :class:`MarkScheme` on disk.
    """

    doc: str
    paper: str
    session: str
    maxMarks: int | None = None
    questionCount: int | None = None
    status: SchemeStatus


class SchemeListDTO(ApiModel):
    """Response for ``GET /api/schemes`` — rows plus computed stats."""

    schemes: list[SchemeRowDTO] = Field(default_factory=list)
    stats: list[StatCardDTO] = Field(default_factory=list)


class QuestionPoolDTO(ApiModel):
    """A question-source pool for the quiz builder.

    Data-backed: ``count`` reflects the real number of available questions in the
    pool (0 when the pool is empty). ``label``/``detail`` describe the pool.
    """

    key: Literal["past", "ai", "mine"]
    label: str
    detail: str
    count: int = 0


class QuizPoolsDTO(ApiModel):
    """Response for ``GET /api/quizzes/pools``."""

    pools: list[QuestionPoolDTO] = Field(default_factory=list)


class QuizTopicDTO(ApiModel):
    """A selectable quiz topic with the marks-lost signal behind it.

    Data-backed: ``topic``, ``marksLost``, ``marksAvailable`` come from the
    aggregate :class:`WeaknessReport`. ``selected`` defaults to ``False`` — the
    mock's pre-checked defaults are presentation state, not backend data.
    """

    topic: str
    marksLost: int
    marksAvailable: int
    selected: bool = False


class QuizTopicsDTO(ApiModel):
    """Response for ``GET /api/quizzes/topics``."""

    topics: list[QuizTopicDTO] = Field(default_factory=list)


class PreviewQuestionDTO(ApiModel):
    """One generated / selected preview question.

    Data-backed: every field is taken from a real :class:`GeneratedQuestion`.
    ``source`` is ``"ai"`` for generated items and ``"existing"`` for selected
    pool items (inferred from ``sourceQuestionIds``).
    """

    topic: str
    difficulty: Literal["foundation", "standard", "challenge"]
    prompt: str
    marks: int
    source: Literal["ai", "existing"]
    sourceQuestionIds: list[str] = Field(default_factory=list)


class QuizPreviewDTO(ApiModel):
    """Response for ``POST /api/quizzes/preview`` and ``/generate``."""

    subjectCode: str
    questions: list[PreviewQuestionDTO] = Field(default_factory=list)
    estMinutes: int = 0


class MasteryRowDTO(ApiModel):
    """Per-topic mastery vs. a reference average.

    Data-backed: ``topic``, ``value`` (class accuracy for the topic). ``national``
    is *structurally-empty* (``None``) — no national benchmark source exists; the
    mock's numbers are not reproduced. ``below`` is computed only when a reference
    is present, otherwise ``False``.
    """

    topic: str
    value: int
    national: int | None = None
    below: bool = False


class DistributionBarDTO(ApiModel):
    """A grade-distribution bar (data-backed count per grade)."""

    grade: str
    count: int


class StudentRowDTO(ApiModel):
    """A class roster row.

    Data-backed: ``name`` (the student's real ``display_name``, falling back to
    ``email`` — D3.1; previously this carried the raw history-key student id),
    ``studentId`` (the real user id, added D3.1 so the frontend can link
    through to student detail without parsing it out of ``name``), ``grade``,
    ``mark`` (awarded/max of latest paper), ``delta`` (percentage change vs.
    prior same paper, ``None`` when no prior), ``weakTopic`` (weakest area of
    the latest paper). ``gradeAtRisk`` is computed from ``grade``.
    """

    name: str
    grade: str
    mark: str
    delta: float | None = None
    weakTopic: str | None = None
    gradeAtRisk: bool = False
    studentId: str = ""


class ClassSummaryDTO(ApiModel):
    """One class in ``GET /api/teacher/classes``.

    Data-backed: ``id``, ``label`` (the class name), ``studentCount``,
    ``average`` (mean latest percentage across enrolled students with
    history). ``subjectCode``/``schoolId``/``joinCode`` are the real class
    model's remaining fields, added D3.1 (optional so older callers keep
    working).
    """

    id: str
    label: str
    studentCount: int
    average: float | None = None
    subjectCode: str | None = None
    schoolId: str | None = None
    joinCode: str | None = None


class ClassListDTO(ApiModel):
    """Response for ``GET /api/teacher/classes``."""

    classes: list[ClassSummaryDTO] = Field(default_factory=list)


class ClassDetailDTO(ApiModel):
    """Response for ``GET /api/classes/{id}``.

    Data-backed: ``stats``, ``mastery`` (per-topic accuracy), ``distribution``
    (grade counts), ``students`` (roster) — all computed over the class's real
    enrolled roster (D3.1), not every student in the store. Fields the mock
    shows without a backend source (bubble predictions, hours-saved
    narratives) are omitted. ``subjectCode``/``schoolId``/``joinCode`` are the
    real class model's remaining fields, added D3.1.
    """

    id: str
    label: str
    stats: list[StatCardDTO] = Field(default_factory=list)
    mastery: list[MasteryRowDTO] = Field(default_factory=list)
    distribution: list[DistributionBarDTO] = Field(default_factory=list)
    students: list[StudentRowDTO] = Field(default_factory=list)
    subjectCode: str | None = None
    schoolId: str | None = None
    joinCode: str | None = None


class AtRiskAcknowledgementDTO(ApiModel):
    """Who/when/note for a flag a teacher has acknowledged (D3.5, T-06).

    Present on an :class:`AtRiskFlagDTO` only when a stored acknowledgement
    exists **and** its evidence fingerprint still matches the flag currently
    firing (:func:`lemely.core.at_risk.flag_fingerprint`) — an acknowledgement
    whose evidence has moved on (a further decline, a fresh submission ending
    an inactivity streak) is not surfaced here; the flag instead renders with
    ``acknowledged: null``, exactly as if it had never been acked, so a
    teacher is never shown reassurance the evidence no longer supports (D3.5:
    "never a permanent mute").

    ``acknowledgedBy`` is the acknowledging teacher's id, not a resolved
    display name — mirrors ``ReviewItemDetailDTO.overriddenBy``/``resolvedBy``,
    the established convention for "who" fields on this wire format.
    Teacher-facing only: this DTO is never populated on any student/parent
    surface (D3.5 — acknowledgements are never student/parent-visible).
    """

    acknowledgedBy: str
    acknowledgedAt: str
    note: str | None = None


class AtRiskFlagDTO(ApiModel):
    """One fired D3.3 at-risk rule, mirroring ``lemely.core.at_risk.AtRiskFlag``.

    ``reason`` is the machine-readable rule id (``declining_trend`` /
    ``below_target`` / ``inactive``); ``summary`` is the human-readable
    sentence the UI can render directly rather than an unexplained badge
    (spec §1.4); ``evidence`` is that rule's structured numbers
    (``percentages``, or ``targetGrade``/``predictedGrade``/``positionsBelow``,
    or ``daysInactive``/``lastActiveAt``) as a plain dict — deliberately not a
    typed union on the wire, since no frontend consumes this yet (P3.7/P3.8).

    ``acknowledged`` (added P3.4b/D3.5) is populated through one shared
    helper (``lemely.web.routers.teacher._at_risk_flag_dto``) on every
    teacher-facing surface that renders a flag — T-01's overview, T-05's
    student detail, T-06's at-risk list — so the same flag never reads
    acknowledged on one screen and unacknowledged on another (the exact
    divergence D3.3/D3.4 each had to fix once already for "at risk" and
    "weaknesses"). Additive field, defaults to ``None`` so older callers
    still deserialise.
    """

    reason: str
    summary: str
    evidence: dict[str, float | int | str | list[float]]
    acknowledged: AtRiskAcknowledgementDTO | None = None


class AtRiskStudentDTO(ApiModel):
    """An at-risk student on the overview.

    Data-backed: ``name`` (student id), ``grade``, ``delta`` (falling trajectory
    signal), ``weakTopic``. The mock's ``tag``/``note``/``action`` narratives have
    no backend source and are omitted. ``flags`` (added D3.3/P3.2) is the real
    reason-labelled output of ``lemely.core.at_risk.assess_at_risk`` — every
    student in this list has at least one flag; additive field, defaults to
    empty so older callers still deserialise.
    """

    name: str
    grade: str
    delta: float | None = None
    weakTopic: str | None = None
    flags: list[AtRiskFlagDTO] = Field(default_factory=list)


class OverviewDTO(ApiModel):
    """Response for ``GET /api/teacher/overview``.

    Data-backed: ``stats`` (from history/analytics) and ``atRisk`` (students on a
    falling trajectory). ``retention`` is *structurally-empty* — lesson-retention
    minutes have no backend source, so the list is always empty rather than
    reproducing the mock's bar heights.
    """

    stats: list[StatCardDTO] = Field(default_factory=list)
    atRisk: list[AtRiskStudentDTO] = Field(default_factory=list)
    retention: list[int] = Field(default_factory=list)


class AcknowledgeAtRiskRequestDTO(ApiModel):
    """Body for ``POST /api/teacher/at-risk/{student_id}/acknowledge`` (T-06).

    ``reason`` must name a rule (``lemely.core.at_risk.AtRiskReason`` value)
    currently firing for this student — acknowledging a rule that is not
    presently raised for them is rejected (422): there is no flag to
    acknowledge, so nothing here would correspond to anything the teacher
    could have seen. ``note`` is optional and teacher-facing only (D3.5).
    """

    reason: str
    note: str | None = None


__all__ = [
    "AcknowledgeAtRiskRequestDTO",
    "AtRiskAcknowledgementDTO",
    "AtRiskStudentDTO",
    "BatchTabDTO",
    "ClassDetailDTO",
    "ClassListDTO",
    "ClassSummaryDTO",
    "DetectedFieldDTO",
    "DistributionBarDTO",
    "GradingQueueDTO",
    "MasteryRowDTO",
    "OverviewDTO",
    "PaperDetailDTO",
    "PaperKind",
    "PaperListDTO",
    "PaperSummaryDTO",
    "PipelineStepDTO",
    "PreviewQuestionDTO",
    "QuestionPoolDTO",
    "QueueRowDTO",
    "QuizPoolsDTO",
    "QuizPreviewDTO",
    "QuizTopicDTO",
    "QuizTopicsDTO",
    "SchemeListDTO",
    "SchemeRowDTO",
    "SchemeStatus",
    "StatCardDTO",
    "StudentRowDTO",
    "UploadResponseDTO",
]
