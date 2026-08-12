"""Parent-portal API DTOs (camelCase wire format, P3.6 chunk A).

Covers ``docs/LEMELY_UI_SPEC.md`` §4.8's four parent screens — P-01 (children
list), P-02 (child overview), P-03 (child subject detail), P-04 (child
weaknesses) — plus the parent-link request/response DTOs shared by the
student-side invite/list/revoke routes (``lemely.web.routers.student``) and
the parent-side routes (``lemely.web.routers.parent``). Kept out of
``lemely.web.schemas_student`` deliberately: these are not student-portal-
shaped, they are the two ends of one relationship.

**Data provenance.** Every field is documented as data-backed (computed from
:class:`~lemely.core.history.StudentHistory` via
:mod:`lemely.core.analytics`/:mod:`lemely.core.at_risk`, or from
:class:`~lemely.db.class_repo.ClassService`) or, where the UI spec asks for a
signal this codebase has no source for, omitted entirely — see
``lemely.web.routers.parent``'s module docstring for the itemised list.
Plain-language fields (``statusLine``, weak-topic phrasing) are translations
of real data, never invented confidence language (UI spec §1.4).
"""

from __future__ import annotations

from pydantic import Field

from lemely.web.schemas import ApiModel

# ── Parent-link DTOs (shared: student-invite routes + parent-facing routes) ──


class LinkedParentDTO(ApiModel):
    """One parent linked to the authenticated student.

    Data-backed: ``parentId``/``displayName``/``phone`` come straight off the
    linked ``users`` row (:class:`~lemely.db.parent_repo.ParentRow`).
    """

    parentId: str
    displayName: str
    phone: str | None = None


class ParentLinkListDTO(ApiModel):
    """Response for ``GET /api/student/parent-links``."""

    parents: list[LinkedParentDTO] = Field(default_factory=list)


class LinkParentRequestDTO(ApiModel):
    """Body for ``POST /api/student/parent-links`` — invite an existing parent by phone.

    Resolves to an *existing* ``role=parent`` user only (D3.11) — this never
    creates an account from a student-supplied phone.
    """

    phone: str


# ── P-01: parent home / children ─────────────────────────────────────────────


class ChildClassDTO(ApiModel):
    """One class a child is enrolled in (data-backed, via ``ClassService``).

    ``schoolName`` is ``None`` for an independent teacher's class — never a
    fabricated placeholder.
    """

    name: str
    subjectCode: str | None = None
    schoolName: str | None = None


class ChildSummaryDTO(ApiModel):
    """One linked child on the parent home screen (P-01).

    Data-backed throughout: ``classes`` is the child's real enrolled classes
    (:meth:`~lemely.db.class_repo.ClassService.student_classes`).
    ``statusLine`` is a plain-language *translation* of the child's real
    grade-bearing subjects/at-risk flags — never an invented judgement
    ("on track", "struggling") the data does not support; see the router for
    exactly how it is composed. ``trend`` is the percentage-point delta
    between the child's most recent grade-bearing paper and the same paper's
    prior attempt (``None`` when there is no such pair — the same "paper
    comparison" notion :func:`~lemely.core.analytics.compare_performance`
    already defines). ``lastActivityAt`` is the most recent record of any
    kind (quizzes count as activity, D3.9) — ``None`` when the child has no
    recorded activity at all.
    """

    childId: str
    displayName: str
    classes: list[ChildClassDTO] = Field(default_factory=list)
    statusLine: str
    trend: float | None = None
    lastActivityAt: str | None = None


class ChildListDTO(ApiModel):
    """Response for ``GET /api/parent/children`` (P-01)."""

    children: list[ChildSummaryDTO] = Field(default_factory=list)


# ── Shared across P-02/P-03/P-04 ─────────────────────────────────────────────


class ParentAtRiskFlagDTO(ApiModel):
    """One fired D3.3 at-risk rule, translated for a parent (P-02).

    Mirrors ``lemely.web.schemas_teacher.AtRiskFlagDTO`` in shape
    (``reason``/``summary``/``evidence``) but **deliberately omits
    ``acknowledged``** — acknowledgement is teacher-facing only (D3.5: "the
    ack note is teacher-facing and never student-visible"; parents were never
    in D3.5's scope), so this DTO carries nothing about it rather than a
    field that would always read ``null``.
    """

    reason: str
    summary: str
    evidence: dict[str, float | int | str | list[float]]


class WeakTopicDTO(ApiModel):
    """One weak topic, phrased plainly (mirrors core ``WeakArea``).

    ``lostMarks``/``maximumMarks``/``accuracy`` are the real aggregate
    numbers (:func:`~lemely.core.analytics.aggregate_weaknesses_from_history`)
    — "phrased plainly" is the router's job (topic name + these three
    numbers, no jargon), not a rewritten string on the wire.
    """

    topic: str
    lostMarks: int
    maximumMarks: int
    accuracy: float


class RecentPaperDTO(ApiModel):
    """One recorded paper (grade-bearing only — a paper claim, D3.9)."""

    paperId: str
    subjectCode: str
    subjectName: str
    marks: str
    grade: str
    recordedAt: str


class ChildActivityDTO(ApiModel):
    """A child's own activity stats (data-backed, from ``recorded_at``).

    ``totalPapers`` counts only real past papers (``is_paper``); it says
    *papers*, so it says so honestly. ``lastActiveAt``/``daysSinceLastActivity``
    read **all** records — a quiz is activity too (D3.9) — so this never
    disagrees with the at-risk inactivity rule sitting beside it.
    """

    totalPapers: int
    lastActiveAt: str | None = None
    daysSinceLastActivity: int | None = None


# ── P-02: child overview ─────────────────────────────────────────────────────


class SubjectTrendPointDTO(ApiModel):
    """One point in a subject's percentage-over-time series (grade-bearing only)."""

    recordedAt: str
    percentage: float


class SubjectOverviewDTO(ApiModel):
    """One subject's standing on the child overview (P-02).

    ``subjectName`` is a translated name (``lemely.io.det.profiles.get_profile``),
    falling back to the raw code when unknown — never invented. ``target`` is
    **always ``null``**: there is no target-grade column anywhere in the
    schema yet (Phase 4's onboarding questionnaire, D3.3) — this is the same
    "not evaluable" honesty ``lemely.core.at_risk`` already applies to its
    below-target rule, not a default or a value derived from
    ``predictedGrade``. ``trend`` is this subject's percentage-over-time
    series across grade-bearing papers, oldest first.
    """

    subjectCode: str
    subjectName: str
    predictedGrade: str
    target: str | None = None
    latestPercentage: float
    paperCount: int
    trend: list[SubjectTrendPointDTO] = Field(default_factory=list)


class ChildOverviewDTO(ApiModel):
    """Response for ``GET /api/parent/children/{child_id}`` (P-02).

    Data-backed throughout: ``subjects`` (predicted grade, real ``target``
    honesty, trend), ``recentPapers`` (grade-bearing only), ``weakTopics``
    (aggregate across *all* records, quizzes included — D3.9 topic
    aggregation is deliberately unfiltered), ``activity``, ``atRiskFlags``
    (the D3.3 rules engine, translated via ``ParentAtRiskFlagDTO``).
    """

    childId: str
    displayName: str
    subjects: list[SubjectOverviewDTO] = Field(default_factory=list)
    recentPapers: list[RecentPaperDTO] = Field(default_factory=list)
    weakTopics: list[WeakTopicDTO] = Field(default_factory=list)
    activity: ChildActivityDTO
    atRiskFlags: list[ParentAtRiskFlagDTO] = Field(default_factory=list)


# ── P-03: child subject detail ───────────────────────────────────────────────


class SubjectPaperDTO(ApiModel):
    """One recorded paper for this subject (grade-bearing only)."""

    paperId: str
    marks: str
    grade: str
    recordedAt: str


class GradeBoundaryDistanceDTO(ApiModel):
    """Distance from the latest paper to the next grade up (P-03).

    Generalizes ``student.py``'s A-boundary-only rail computation
    (``_result_header_fields``) to "the next grade up from whatever grade
    the child is currently on" — a parent reading "3 marks from an A" needs
    the grade *above* the child's own, not always the A boundary
    specifically. ``marksNeeded`` is clamped to zero (never negative) and
    this DTO is omitted entirely when the child is already on the best grade
    (``A*``) or the boundary table has no threshold for ``nextGrade``.
    """

    nextGrade: str
    marksNeeded: int
    summary: str


class SubjectDetailDTO(ApiModel):
    """Response for ``GET /api/parent/children/{child_id}/subjects/{code}`` (P-03).

    Data-backed throughout: ``papers`` (grade-bearing only), ``predictedGrade``
    (latest paper's grade), ``boundaryDistance`` (``None`` when not
    computable — see :class:`GradeBoundaryDistanceDTO`), ``weakTopics``
    (this subject's records, quizzes of the same subject included — D3.9).
    """

    childId: str
    subjectCode: str
    subjectName: str
    predictedGrade: str
    papers: list[SubjectPaperDTO] = Field(default_factory=list)
    boundaryDistance: GradeBoundaryDistanceDTO | None = None
    weakTopics: list[WeakTopicDTO] = Field(default_factory=list)


# ── P-04: child weaknesses ───────────────────────────────────────────────────


class ChildWeaknessesDTO(ApiModel):
    """Response for ``GET /api/parent/children/{child_id}/weaknesses`` (P-04).

    ``weakTopics`` is ranked worst-accuracy-first (the aggregate is
    unfiltered — every recorded weak area, quizzes included, D3.9).
    **The UI spec's "constructive framing on what the child is doing about
    it (practice generated, sessions planned)" is omitted** — there is no
    existing link between a stored study-plan/quiz-generation state and a
    *child viewed by a parent* (the study-plan machinery is keyed by the
    authenticated caller, never by a caller-supplied child id), so shipping
    it would mean fabricating a "sessions planned: 0" placeholder rather
    than a real signal. See ``lemely.web.routers.parent``'s module docstring.
    """

    childId: str
    weakTopics: list[WeakTopicDTO] = Field(default_factory=list)


__all__ = [
    "ChildActivityDTO",
    "ChildClassDTO",
    "ChildListDTO",
    "ChildOverviewDTO",
    "ChildSummaryDTO",
    "ChildWeaknessesDTO",
    "GradeBoundaryDistanceDTO",
    "LinkParentRequestDTO",
    "LinkedParentDTO",
    "ParentAtRiskFlagDTO",
    "ParentLinkListDTO",
    "RecentPaperDTO",
    "SubjectDetailDTO",
    "SubjectOverviewDTO",
    "SubjectPaperDTO",
    "SubjectTrendPointDTO",
    "WeakTopicDTO",
]
