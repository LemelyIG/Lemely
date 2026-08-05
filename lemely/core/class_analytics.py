"""Cohort (class-wide) analytics for the teacher portal (P3.3, T-04).

Pure functions over ``list[StudentHistory]`` — no I/O, no DB, no clock of its
own (every function that cares about "now" takes it as an injected parameter,
matching :mod:`lemely.core.at_risk`'s style). The web layer
(``lemely.web.routers.classes``) supplies the roster/history data and
translates these snake_case return models into camelCase wire DTOs; this
module never sees a :class:`~lemely.db.class_repo.RosterEntry` or any other
DB-shaped type — display names are passed in as plain strings where needed, so
core stays ignorant of the DB layer (import-linter's layering contract).

**Honesty constraints this module is built around:**

* A :class:`~lemely.core.history.PaperRecord`'s ``weak_areas`` only ever
  contains topics where the student lost at least one mark
  (:func:`lemely.core.analytics.summarize_weaknesses` drops
  ``lost_marks == 0`` topics before persistence). That means this module
  cannot distinguish "this student never attempted this topic" from "this
  student scored 100% on every question on this topic" — both look like "no
  recorded weak-area entry". Rather than guess, every per-student topic
  accuracy this module computes is ``None`` in both cases: an honest "cannot
  assert an accuracy value from what is persisted," never a fabricated 0% or
  100%.
* Grade distribution buckets are always drawn from the full
  :data:`~lemely.core.at_risk.GRADE_ORDER` ladder (including zero counts) so a
  class with nobody on a grade still renders that bucket, rather than a
  frontend having to infer "no bar" from a missing key.
* The trend series never interpolates a value for a gap where nobody
  submitted; a sparse history simply produces a sparse series.
"""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import TYPE_CHECKING

from lemely.core.at_risk import GRADE_ORDER
from lemely.core.schemas import StrictModel

if TYPE_CHECKING:
    from lemely.core.history import StudentHistory


class TopicWeakness(StrictModel):
    """One topic ranked by class-wide marks lost, most-lost-first.

    ``student_ids`` are the students who lost at least one mark on this topic
    somewhere in their recorded history — the affected-students drill-down
    T-04 calls for ("click a weakness -> the list of students affected").
    """

    topic: str
    lost_marks: int
    maximum_marks: int
    accuracy: float
    student_ids: list[str]


class HeatmapCell(StrictModel):
    """One (topic, student) cell of the T-04 weakness heatmap.

    ``accuracy`` is ``None`` when the student has no persisted weak-area entry
    for this topic — see the module docstring for why that is not the same
    thing as 0%, and must never be rendered as one.
    """

    topic: str
    student_id: str
    accuracy: float | None


class GradeDistributionBucket(StrictModel):
    """Count of students whose latest recorded grade is ``grade``."""

    grade: str
    count: int


class TrendPoint(StrictModel):
    """One point in the cohort performance-over-time series.

    ``timestamp`` is the ``recorded_at`` value the point is anchored to;
    ``label`` currently mirrors it verbatim (no calendar-bucketing exists yet —
    the frontend may reformat it, but the backend does not invent a coarser
    granularity than the data supports). ``mean_percentage`` is the mean of
    each contributing student's most recent percentage at or before
    ``timestamp``; ``sample_size`` is how many students that is — a point
    early in a class's life may rest on very few students, and the DTO says so
    rather than implying full-class coverage.
    """

    timestamp: str
    label: str
    mean_percentage: float
    sample_size: int


class PaperComparison(StrictModel):
    """Cohort-wide stats for one paper identity (subject + paper + variant)."""

    paper_id: str
    subject_code: str
    paper_number: int
    paper_variant: int
    mean_percentage: float
    attempt_count: int
    student_count: int


class EngagementStats(StrictModel):
    """Submission-activity stats derived purely from ``recorded_at`` (T-04).

    ``median_days_since_last_submission`` is ``None`` when no student has ever
    submitted a paper (there is nothing to take a median of); students with an
    unparseable ``recorded_at`` on their latest paper are excluded from the
    median for the same reason :func:`lemely.core.at_risk._check_inactivity`
    fails safe on an unparseable timestamp — a value we cannot trust must not
    assert a recency either way.
    """

    submissions_last_7_days: int
    submissions_last_30_days: int
    active_students_last_7_days: int
    active_students_last_30_days: int
    never_active_count: int
    median_days_since_last_submission: float | None


def rank_topic_weaknesses(histories: list[StudentHistory]) -> list[TopicWeakness]:
    """Rank topics by total marks lost across the whole cohort's history.

    Topics with zero total lost marks are excluded (nobody ever lost a mark on
    them, so they carry no signal for "what to teach next week") — mirrors
    :func:`lemely.core.analytics.aggregate_weaknesses_from_history`'s exclusion
    rule, applied cohort-wide instead of per-student. Ties (equal total lost
    marks) are broken alphabetically by topic so the ranking is deterministic.
    """
    lost_by_topic: dict[str, int] = {}
    max_by_topic: dict[str, int] = {}
    students_by_topic: dict[str, set[str]] = {}

    for history in histories:
        for record in history.records:
            for area in record.weak_areas:
                lost_by_topic[area.topic] = lost_by_topic.get(area.topic, 0) + area.lost_marks
                max_by_topic[area.topic] = max_by_topic.get(area.topic, 0) + area.maximum_marks
                if area.lost_marks > 0:
                    students_by_topic.setdefault(area.topic, set()).add(history.student_id)

    weaknesses = []
    for topic, lost_marks in lost_by_topic.items():
        if lost_marks <= 0:
            continue
        maximum_marks = max_by_topic[topic]
        accuracy = 1.0 - (lost_marks / maximum_marks) if maximum_marks else 0.0
        weaknesses.append(
            TopicWeakness(
                topic=topic,
                lost_marks=lost_marks,
                maximum_marks=maximum_marks,
                accuracy=round(accuracy, 4),
                student_ids=sorted(students_by_topic.get(topic, set())),
            )
        )
    weaknesses.sort(key=lambda w: (-w.lost_marks, w.topic))
    return weaknesses


def topic_student_heatmap(
    histories: list[StudentHistory], ranked_topics: list[TopicWeakness]
) -> list[HeatmapCell]:
    """Build topic x student accuracy cells, restricted to ``ranked_topics``.

    Only the already-ranked (class-wide, marks-actually-lost) topics are
    rendered — a topic nobody ever lost marks on has no ranking row and so no
    heatmap row either. One cell per (topic, student) pair, in
    ``ranked_topics`` x ``histories`` order, so the frontend can render a
    dense matrix without re-deriving row/column order itself.
    """
    topics = [w.topic for w in ranked_topics]
    cells: list[HeatmapCell] = []
    for topic in topics:
        for history in histories:
            lost = 0
            maximum = 0
            found = False
            for record in history.records:
                for area in record.weak_areas:
                    if area.topic == topic:
                        found = True
                        lost += area.lost_marks
                        maximum += area.maximum_marks
            accuracy = round(1.0 - (lost / maximum), 4) if found and maximum else None
            cells.append(HeatmapCell(topic=topic, student_id=history.student_id, accuracy=accuracy))
    return cells


def grade_distribution(histories: list[StudentHistory]) -> list[GradeDistributionBucket]:
    """Count students by latest recorded grade over the full grade ladder.

    Every rung of :data:`~lemely.core.at_risk.GRADE_ORDER` is present, zero
    counts included, so a frontend never has to infer "nobody on a B" from a
    missing key. A student with no records contributes to no bucket (they
    have no grade yet); a latest grade that is not on the ladder (malformed
    upstream data) is defensively skipped rather than crashing the endpoint —
    the same judgment call ``lemely.core.at_risk`` makes for an unrecognised
    grade string.
    """
    counts: dict[str, int] = dict.fromkeys(GRADE_ORDER, 0)
    for history in histories:
        if not history.records:
            continue
        grade = history.records[-1].grade
        if grade in counts:
            counts[grade] += 1
    return [GradeDistributionBucket(grade=g, count=counts[g]) for g in GRADE_ORDER]


def cohort_trend(histories: list[StudentHistory]) -> list[TrendPoint]:
    """Compute the cohort mean-percentage series over time.

    One point per distinct ``recorded_at`` timestamp seen anywhere in the
    cohort (chronological — ``recorded_at`` strings are the canonical
    :func:`~lemely.core.history.now_iso` UTC ISO-8601 format, which sorts
    lexicographically in timestamp order). Each point's ``mean_percentage`` is
    the mean, across every student who has submitted at least one paper at or
    before that timestamp, of that student's *most recent* percentage as of
    that point — a running cohort average, never an interpolated guess for a
    student who has not submitted yet. Returns ``[]`` for an empty cohort.
    """
    timestamps = sorted({record.recorded_at for history in histories for record in history.records})
    points: list[TrendPoint] = []
    for timestamp in timestamps:
        latest_by_student: dict[str, float] = {}
        for history in histories:
            eligible = [r for r in history.records if r.recorded_at <= timestamp]
            if eligible:
                latest_by_student[history.student_id] = max(
                    eligible, key=lambda r: r.recorded_at
                ).percentage
        if not latest_by_student:
            continue
        mean_percentage = round(sum(latest_by_student.values()) / len(latest_by_student), 2)
        points.append(
            TrendPoint(
                timestamp=timestamp,
                label=timestamp,
                mean_percentage=mean_percentage,
                sample_size=len(latest_by_student),
            )
        )
    return points


def per_paper_comparison(histories: list[StudentHistory]) -> list[PaperComparison]:
    """Group every recorded attempt by paper identity (subject + paper + variant).

    ``attempt_count`` counts every attempt (a student who resat a paper counts
    twice); ``student_count`` counts distinct students. Sorted by subject code
    then paper number then variant for a stable, deterministic ordering.
    """
    pcts: dict[tuple[str, int, int], list[float]] = {}
    students: dict[tuple[str, int, int], set[str]] = {}

    for history in histories:
        for record in history.records:
            key = (
                record.metadata.subject_code,
                record.metadata.paper_number,
                record.metadata.paper_variant,
            )
            pcts.setdefault(key, []).append(record.percentage)
            students.setdefault(key, set()).add(history.student_id)

    comparisons = []
    for (subject_code, paper_number, paper_variant), percentages in pcts.items():
        comparisons.append(
            PaperComparison(
                paper_id=f"{subject_code}/{paper_number}{paper_variant}",
                subject_code=subject_code,
                paper_number=paper_number,
                paper_variant=paper_variant,
                mean_percentage=round(sum(percentages) / len(percentages), 2),
                attempt_count=len(percentages),
                student_count=len(students[(subject_code, paper_number, paper_variant)]),
            )
        )
    comparisons.sort(key=lambda c: (c.subject_code, c.paper_number, c.paper_variant))
    return comparisons


# Engagement windows, in days. Named so the boundary semantics ("submitted
# strictly less than N days ago") are stated once rather than re-literalised
# at each call site.
_ENGAGEMENT_WINDOW_DAYS = (7, 30)


def engagement_stats(histories: list[StudentHistory], *, now: datetime) -> EngagementStats:
    """Compute submission/activity stats purely from ``recorded_at`` values.

    A paper counts in a window when ``(now - recorded_at).days < window_days``
    (day 6 is inside the 7-day window, day 7 is not) — the injected ``now`` is
    required, mirroring :func:`lemely.core.at_risk.assess_at_risk`, so this
    function is deterministic under test. A student with zero records is
    "never active"; one whose latest ``recorded_at`` cannot be parsed (see
    :class:`EngagementStats`) is active (they did submit) but excluded from
    the median.
    """
    submissions_7 = 0
    submissions_30 = 0
    active_7: set[str] = set()
    active_30: set[str] = set()
    never_active = 0
    days_since_last: list[int] = []

    for history in histories:
        if not history.records:
            never_active += 1
            continue
        for record in history.records:
            recorded = _parse_recorded_at(record.recorded_at)
            if recorded is None:
                continue
            days_ago = (now - recorded).days
            if days_ago < _ENGAGEMENT_WINDOW_DAYS[0]:
                submissions_7 += 1
                active_7.add(history.student_id)
            if days_ago < _ENGAGEMENT_WINDOW_DAYS[1]:
                submissions_30 += 1
                active_30.add(history.student_id)
        last_active = _parse_recorded_at(history.records[-1].recorded_at)
        if last_active is not None:
            days_since_last.append((now - last_active).days)

    return EngagementStats(
        submissions_last_7_days=submissions_7,
        submissions_last_30_days=submissions_30,
        active_students_last_7_days=len(active_7),
        active_students_last_30_days=len(active_30),
        never_active_count=never_active,
        median_days_since_last_submission=(
            float(median(days_since_last)) if days_since_last else None
        ),
    )


def _parse_recorded_at(value: str) -> datetime | None:
    """Defensively parse a ``PaperRecord.recorded_at`` ISO string.

    Duplicated (not imported) from ``lemely.core.at_risk._parse_recorded_at``
    deliberately: both ``lemely.db.history_repo`` and ``lemely.db.attempt_repo``
    already carry their own private copy of this exact defensive-parse
    pattern, so a third private copy here follows the established convention
    rather than reaching across modules for a leading-underscore helper.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


__all__ = [
    "EngagementStats",
    "GradeDistributionBucket",
    "HeatmapCell",
    "PaperComparison",
    "TopicWeakness",
    "TrendPoint",
    "cohort_trend",
    "engagement_stats",
    "grade_distribution",
    "per_paper_comparison",
    "rank_topic_weaknesses",
    "topic_student_heatmap",
]
