from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from lemely.core.history import PaperRecord, PerformanceComparison, StudentHistory

from lemely.core.schemas import (
    ConfidenceBand,
    CorrectionResult,
    GradePrediction,
    QuizPayload,
    QuizQuestion,
    WeakArea,
    WeaknessReport,
)


class _TopicBucket(TypedDict):
    awarded_marks: int
    lost_marks: int
    maximum_marks: int
    question_ids: list[str]


DEFAULT_GRADE_BOUNDARIES = {
    "A": 80.0,
    "B": 70.0,
    "C": 60.0,
    "D": 50.0,
    "E": 40.0,
}


def summarize_weaknesses(correction: CorrectionResult) -> WeaknessReport:
    grouped: dict[str, _TopicBucket] = {}
    for question in correction.questions:
        lost_marks = question.maximum_marks - question.awarded_marks
        topic = question.topic or "unknown"
        bucket = grouped.setdefault(
            topic,
            _TopicBucket(awarded_marks=0, lost_marks=0, maximum_marks=0, question_ids=[]),
        )
        bucket["awarded_marks"] += question.awarded_marks
        bucket["lost_marks"] += lost_marks
        bucket["maximum_marks"] += question.maximum_marks
        if lost_marks > 0:
            bucket["question_ids"].append(question.question_id)

    weak_areas = []
    for topic, bucket in grouped.items():
        maximum_marks = bucket["maximum_marks"]
        lost_marks = bucket["lost_marks"]
        if lost_marks <= 0:
            continue
        accuracy = 1.0 - (lost_marks / maximum_marks) if maximum_marks else 1.0
        weak_areas.append(
            WeakArea(
                topic=topic,
                lost_marks=lost_marks,
                maximum_marks=maximum_marks,
                accuracy=accuracy,
                question_ids=bucket["question_ids"],
            )
        )

    weak_areas.sort(key=lambda area: (area.accuracy, area.topic))
    return WeaknessReport(
        weak_areas=weak_areas,
        needs_teacher_review=correction.needs_teacher_review,
    )


def predict_grade(
    correction: CorrectionResult,
    boundaries: dict[str, float] | None = None,
    boundary_source: str = "global_default",
) -> GradePrediction:
    active_boundaries = boundaries or DEFAULT_GRADE_BOUNDARIES
    percentage = (
        (correction.awarded_marks / correction.maximum_marks) * 100.0
        if correction.maximum_marks
        else 0.0
    )
    grade = "U"
    for candidate, threshold in sorted(
        active_boundaries.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        if percentage >= threshold:
            grade = candidate
            break

    return GradePrediction(
        awarded_marks=correction.awarded_marks,
        maximum_marks=correction.maximum_marks,
        percentage=round(percentage, 2),
        grade=grade,
        confidence=ConfidenceBand.LOW if correction.needs_teacher_review else ConfidenceBand.MEDIUM,
        needs_teacher_review=correction.needs_teacher_review,
        boundary_source=boundary_source,
    )


def generate_quiz(weaknesses: WeaknessReport, question_count: int = 5) -> QuizPayload:
    questions = [
        QuizQuestion(
            topic=area.topic,
            prompt=f"Practice a targeted question on {area.topic}.",
            source_question_ids=area.question_ids,
        )
        for area in weaknesses.weak_areas[:question_count]
    ]
    return QuizPayload(questions=questions)


def compare_performance(
    history: StudentHistory,
    latest: PaperRecord,
) -> PerformanceComparison:
    """Compare the latest paper against prior attempts of the same subject+paper.

    Args:
        history: The student's recorded paper history.
        latest: The most recent paper result (not yet appended to history).

    Returns:
        PerformanceComparison with percentage_delta vs. most recent prior attempt.
        percentage_delta is None when no prior attempt exists for the same paper.
    """
    from lemely.core.history import PerformanceComparison, TopicTrend

    same_paper = [
        r
        for r in history.records
        if r.metadata.subject_code == latest.metadata.subject_code
        and r.metadata.paper_number == latest.metadata.paper_number
    ]

    percentage_delta: float | None = None
    topic_trends: list[TopicTrend] = []

    if same_paper:
        prior = same_paper[-1]
        percentage_delta = round(latest.percentage - prior.percentage, 2)

        prior_by_topic = {a.topic: a for a in prior.weak_areas}
        for area in latest.weak_areas:
            if area.topic in prior_by_topic:
                delta = area.accuracy - prior_by_topic[area.topic].accuracy
                if delta > 0.02:
                    direction = "improving"
                elif delta < -0.02:
                    direction = "declining"
                else:
                    direction = "stable"
                topic_trends.append(
                    TopicTrend(
                        topic=area.topic, direction=direction, delta_accuracy=round(delta, 4)
                    )
                )

    return PerformanceComparison(
        student_id=latest.student_id,
        latest=latest,
        prior_count=len(same_paper),
        percentage_delta=percentage_delta,
        topic_trends=topic_trends,
    )


def aggregate_weaknesses_from_history(history: StudentHistory) -> WeaknessReport:
    """Fold all PaperRecord.weak_areas into an aggregate WeaknessReport.

    Groups by topic, sums lost_marks and maximum_marks across papers,
    recomputes accuracy = 1 - (total_lost / total_max), merges question_ids.
    Topics with total lost_marks == 0 are excluded (consistent with summarize_weaknesses).
    Returns an empty WeaknessReport when history has no records.
    """
    # topic → {lost_marks, maximum_marks, question_ids}
    buckets: dict[str, _TopicBucket] = {}

    for record in history.records:
        for area in record.weak_areas:
            if area.topic not in buckets:
                buckets[area.topic] = {
                    "awarded_marks": 0,
                    "lost_marks": 0,
                    "maximum_marks": 0,
                    "question_ids": [],
                }
            b = buckets[area.topic]
            b["lost_marks"] += area.lost_marks
            b["maximum_marks"] += area.maximum_marks
            b["question_ids"].extend(area.question_ids)

    weak_areas = []
    for topic, b in buckets.items():
        if b["lost_marks"] == 0:
            continue
        max_m = b["maximum_marks"]
        accuracy = 1.0 - (b["lost_marks"] / max_m) if max_m else 0.0
        weak_areas.append(
            WeakArea(
                topic=topic,
                lost_marks=b["lost_marks"],
                maximum_marks=max_m,
                accuracy=round(accuracy, 4),
                question_ids=list(dict.fromkeys(b["question_ids"])),
            )
        )

    return WeaknessReport(weak_areas=weak_areas)
