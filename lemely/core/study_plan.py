"""Pure study-plan scheduler — no I/O, no Gemini calls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.study import StudentProfile, StudyPlan, StudySession

if TYPE_CHECKING:
    from lemely.core.schemas import WeaknessReport


def build_study_plan(
    profile: StudentProfile | None,
    weaknesses: WeaknessReport,
    *,
    weekly_hours: float,
) -> StudyPlan:
    """Distribute weekly study hours across weak topics proportionally to lost_marks.

    Topics with lost_marks == 0 are excluded entirely.
    Total allocated hours ≈ weekly_hours (rounding tolerance: ±1 session).

    Args:
        profile: Optional student profile (used for student_id and subject context).
        weaknesses: WeaknessReport with topics to prioritise.
        weekly_hours: Hours available per week.

    Returns:
        StudyPlan with one StudySession per non-zero-loss topic.
    """
    student_id = profile.student_id if profile else "unknown"
    subject_code = profile.subjects[0] if (profile and profile.subjects) else "unknown"

    eligible = [a for a in weaknesses.weak_areas if a.lost_marks > 0]

    if not eligible:
        return StudyPlan(
            student_id=student_id,
            weekly_hours=weekly_hours,
            sessions=[],
        )

    total_lost = sum(a.lost_marks for a in eligible)
    sessions: list[StudySession] = []

    remaining_hours = weekly_hours
    for i, area in enumerate(eligible):
        is_last = i == len(eligible) - 1
        if is_last:
            hours = remaining_hours
        else:
            proportion = area.lost_marks / total_lost
            hours = round(proportion * weekly_hours, 1)
            remaining_hours -= hours
        if hours <= 0:
            hours = 0.0
        sessions.append(
            StudySession(
                week=1,
                topic=area.topic,
                subject_code=subject_code,
                hours=hours,
                focus=f"Practice and review: {area.topic}",
            )
        )

    return StudyPlan(
        student_id=student_id,
        weekly_hours=weekly_hours,
        sessions=sessions,
    )
