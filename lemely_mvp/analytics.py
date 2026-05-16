from __future__ import annotations

from .schemas import (
    ConfidenceBand,
    CorrectionResult,
    GradePrediction,
    QuizPayload,
    QuizQuestion,
    WeakArea,
    WeaknessReport,
)

DEFAULT_GRADE_BOUNDARIES = {
    "A": 80.0,
    "B": 70.0,
    "C": 60.0,
    "D": 50.0,
    "E": 40.0,
}


def summarize_weaknesses(correction: CorrectionResult) -> WeaknessReport:
    grouped: dict[str, dict[str, object]] = {}
    for question in correction.questions:
        lost_marks = question.maximum_marks - question.awarded_marks
        topic = question.topic or "unknown"
        bucket = grouped.setdefault(
            topic,
            {"awarded_marks": 0, "lost_marks": 0, "maximum_marks": 0, "question_ids": []},
        )
        bucket["awarded_marks"] = int(bucket["awarded_marks"]) + question.awarded_marks
        bucket["lost_marks"] = int(bucket["lost_marks"]) + lost_marks
        bucket["maximum_marks"] = int(bucket["maximum_marks"]) + question.maximum_marks
        if lost_marks > 0:
            question_ids = bucket["question_ids"]
            if isinstance(question_ids, list):
                question_ids.append(question.question_id)

    weak_areas = []
    for topic, bucket in grouped.items():
        maximum_marks = int(bucket["maximum_marks"])
        lost_marks = int(bucket["lost_marks"])
        if lost_marks <= 0:
            continue
        accuracy = 1.0 - (lost_marks / maximum_marks) if maximum_marks else 1.0
        weak_areas.append(
            WeakArea(
                topic=topic,
                lost_marks=lost_marks,
                maximum_marks=maximum_marks,
                accuracy=accuracy,
                question_ids=list(bucket["question_ids"]),
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
