"""Teacher analytics API DTOs (camelCase wire format, P3.3).

Covers three screens from ``docs/LEMELY_UI_SPEC.md``:

* **T-04** (class detail — analytics): :class:`ClassAnalyticsDTO`, served by
  ``GET /api/classes/{class_id}/analytics``.
* **T-05** (student detail, teacher view): :class:`StudentDetailDTO`, served
  by ``GET /api/teacher/students/{student_id}``.
* **T-06** (at-risk list): :class:`AtRiskListDTO`, served by
  ``GET /api/teacher/at-risk``.

Every field mirrors a snake_case core model 1:1 (``lemely.core.class_analytics``,
``lemely.core.at_risk``, ``lemely.core.analytics``) via an explicit converter in
the owning router — nothing here is fabricated. Where the UI spec asks for a
signal with no backend source (T-05's integrity flags — history records carry
no per-question data, only a live, in-process grading run does, and that is
not addressable by a real student id yet), the field is omitted entirely
rather than shipped as an always-empty stub; see the router docstring for the
full reasoning.
"""

from __future__ import annotations

from pydantic import Field

from lemely.web.schemas import ApiModel
from lemely.web.schemas_teacher import AtRiskFlagDTO

# ── T-04: class analytics ────────────────────────────────────────────────────


class TopicWeaknessDTO(ApiModel):
    """One topic ranked by class-wide marks lost (mirrors core ``TopicWeakness``).

    ``studentIds`` backs the "click a weakness -> affected students" drill-down
    (T-04's interaction spec) without a second round-trip.
    """

    topic: str
    lostMarks: int
    maximumMarks: int
    accuracy: float
    studentIds: list[str] = Field(default_factory=list)


class HeatmapCellDTO(ApiModel):
    """One topic x student accuracy cell (mirrors core ``HeatmapCell``).

    ``accuracy`` is ``None`` when the student has no persisted weak-area entry
    for this topic — never fabricated as 0% (UI-spec §1.4, "never invent
    precision").
    """

    topic: str
    studentId: str
    accuracy: float | None = None


class GradeDistributionBucketDTO(ApiModel):
    """Count of students on one grade (mirrors core ``GradeDistributionBucket``)."""

    grade: str
    count: int


class TrendPointDTO(ApiModel):
    """One point in the cohort trend series (mirrors core ``TrendPoint``)."""

    timestamp: str
    label: str
    meanPercentage: float
    sampleSize: int


class PaperComparisonDTO(ApiModel):
    """Per-paper cohort stats (mirrors core ``PaperComparison``)."""

    paperId: str
    subjectCode: str
    paperNumber: int
    paperVariant: int
    meanPercentage: float
    attemptCount: int
    studentCount: int


class EngagementStatsDTO(ApiModel):
    """Submission-activity stats (mirrors core ``EngagementStats``)."""

    submissionsLast7Days: int
    submissionsLast30Days: int
    activeStudentsLast7Days: int
    activeStudentsLast30Days: int
    neverActiveCount: int
    medianDaysSinceLastSubmission: float | None = None


class ClassAnalyticsDTO(ApiModel):
    """Response for ``GET /api/classes/{class_id}/analytics`` (T-04).

    Every field is computed over the class's real enrolled roster (never every
    student in the store), reusing ``lemely.core.class_analytics`` so this
    endpoint cannot drift from the pure cohort-analytics functions it wraps.
    """

    topicWeaknesses: list[TopicWeaknessDTO] = Field(default_factory=list)
    heatmap: list[HeatmapCellDTO] = Field(default_factory=list)
    gradeDistribution: list[GradeDistributionBucketDTO] = Field(default_factory=list)
    trend: list[TrendPointDTO] = Field(default_factory=list)
    paperComparison: list[PaperComparisonDTO] = Field(default_factory=list)
    engagement: EngagementStatsDTO


# ── T-05: student detail (teacher view) ─────────────────────────────────────


class SubjectPredictionDTO(ApiModel):
    """One subject's predicted grade for this student.

    ``predictedGrade`` is the student's latest recorded grade for the subject —
    the same domain notion of "predicted grade" ``lemely.core.at_risk`` already
    uses for its below-target rule (``history.records[-1].grade``), not a
    second, differently-computed forecast.
    """

    subjectCode: str
    predictedGrade: str
    latestPercentage: float
    paperCount: int


class AttemptDTO(ApiModel):
    """One recorded paper attempt, newest first."""

    paperId: str
    subjectCode: str
    paperNumber: int
    paperVariant: int
    awardedMarks: int
    maximumMarks: int
    percentage: float
    grade: str
    recordedAt: str


class StudentWeaknessDTO(ApiModel):
    """One weak topic with its evidence (mirrors core ``WeakArea``)."""

    topic: str
    lostMarks: int
    maximumMarks: int
    accuracy: float
    questionIds: list[str] = Field(default_factory=list)


class StudentTrendPointDTO(ApiModel):
    """One point in this student's own percentage-over-time series."""

    recordedAt: str
    percentage: float


class StudentEngagementDTO(ApiModel):
    """This student's own activity stats (data-backed, from ``recorded_at``)."""

    totalPapers: int
    lastActiveAt: str | None = None
    daysSinceLastSubmission: int | None = None


class StudentDetailDTO(ApiModel):
    """Response for ``GET /api/teacher/students/{student_id}`` (T-05).

    Data-backed throughout: ``subjects`` (predicted grade per subject),
    ``attempts`` (full history), ``weaknesses`` (aggregate, with evidence),
    ``trend`` (this student's own percentage series), ``atRisk``/``atRiskFlags``
    (the D3.3 rules engine, reusing ``assess_at_risk`` and
    ``_at_risk_flag_dto`` — never a re-implemented translation), ``engagement``.
    Integrity signals are deliberately absent: a persisted history record has
    no per-question answers, so plagiarism/AI-content checks (which run only in
    the live, in-process grading flow) cannot be recomputed here — see the
    router docstring.
    """

    studentId: str
    displayName: str
    subjects: list[SubjectPredictionDTO] = Field(default_factory=list)
    attempts: list[AttemptDTO] = Field(default_factory=list)
    weaknesses: list[StudentWeaknessDTO] = Field(default_factory=list)
    trend: list[StudentTrendPointDTO] = Field(default_factory=list)
    isAtRisk: bool = False
    atRiskFlags: list[AtRiskFlagDTO] = Field(default_factory=list)
    engagement: StudentEngagementDTO


# ── T-06: at-risk list ───────────────────────────────────────────────────────


class AtRiskListEntryDTO(ApiModel):
    """One flagged student across the caller's classes (T-06).

    ``classId``/``className`` give the class context the list is grouped by;
    ``flags`` reuses the same ``AtRiskFlagDTO`` shape the overview and class
    detail already carry, so a flag renders identically everywhere it appears.
    """

    studentId: str
    displayName: str
    classId: str
    className: str
    grade: str
    flags: list[AtRiskFlagDTO] = Field(default_factory=list)


class AtRiskListDTO(ApiModel):
    """Response for ``GET /api/teacher/at-risk`` (T-06).

    Sorted by severity: flag count descending, then worst (highest-index-on-
    ``GRADE_ORDER``) grade first — see the router docstring for the full
    rationale. Supports filtering by ``reason`` via a query parameter; this DTO
    carries only the already-filtered/sorted result.
    """

    students: list[AtRiskListEntryDTO] = Field(default_factory=list)


__all__ = [
    "AtRiskListDTO",
    "AtRiskListEntryDTO",
    "AttemptDTO",
    "ClassAnalyticsDTO",
    "EngagementStatsDTO",
    "GradeDistributionBucketDTO",
    "HeatmapCellDTO",
    "PaperComparisonDTO",
    "StudentDetailDTO",
    "StudentEngagementDTO",
    "StudentTrendPointDTO",
    "StudentWeaknessDTO",
    "SubjectPredictionDTO",
    "TopicWeaknessDTO",
    "TrendPointDTO",
]
