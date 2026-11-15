"""Pure helpers behind ``GET /api/student/subject/{code}``'s steps path (redesign L2).

Kept out of :mod:`lemely.web.routers.student` so every rule here is a plain
unit test with no app, store or database: the goal line from a boundary map,
the labels a student reads under each bar, and "marks to win" per topic.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING

from lemely.core.history import is_grade_bearing
from lemely.web.schemas_student import GoalLineDTO, PaperAttemptDTO

if TYPE_CHECKING:
    from lemely.core.history import PaperRecord
    from lemely.core.schemas import ExamMetadata
    from lemely.io.grade_boundaries import BoundarySource

GOAL_GRADE = "A*"

_SESSION_SHORT: dict[str, str] = {
    "May/June": "May/Jun",
    "Oct/Nov": "Oct/Nov",
    "Feb/Mar": "Feb/Mar",
    "Specimen": "Specimen",
}

_FALLBACK_SOURCE_LABEL: dict[str, str] = {
    "subject_default": "Average of past boundaries",
    "global_default": "Estimated boundary",
}


def _half_up(value: float) -> int:
    """Round half away from zero for non-negative values (``round`` rounds to even)."""
    return math.floor(value + 0.5)


def session_label(metadata: ExamMetadata) -> str:
    """``"May/Jun 2024"``; the short month alone when the session has no year."""
    short = _SESSION_SHORT[metadata.session_month]
    return f"{short} {metadata.session_year}" if metadata.session_year is not None else short


def paper_code_label(metadata: ExamMetadata) -> str:
    """``"0580/42 · May/Jun 2024"``: code, paper and variant, then the session."""
    return (
        f"{metadata.subject_code}/{metadata.paper_number}{metadata.paper_variant}"
        f" · {session_label(metadata)}"
    )


def goal_line(
    boundaries: dict[str, float],
    source: BoundarySource,
    metadata: ExamMetadata,
    maximum: int,
) -> GoalLineDTO | None:
    """The A* line (or the paper's top grade) in raw marks, or ``None``.

    ``boundaries`` is :meth:`GradeBoundaryStore.resolve`'s percentage map for
    the paper's latest attempt; ``maximum`` is that attempt's maximum marks.
    """
    if not boundaries or maximum <= 0:
        return None
    grade = GOAL_GRADE if GOAL_GRADE in boundaries else max(boundaries, key=boundaries.__getitem__)
    marks = _half_up(boundaries[grade] / 100.0 * maximum)
    label = (
        f"{session_label(metadata)} boundary"
        if source == "exact"
        else _FALLBACK_SOURCE_LABEL[source]
    )
    return GoalLineDTO(grade=grade, marks=marks, outOf=maximum, source=source, sourceLabel=label)


def attempt_dto(index: int, record: PaperRecord) -> PaperAttemptDTO:
    """One bar on the path. ``index`` is the record's FULL-history position."""
    return PaperAttemptDTO(
        id=str(index),
        recordedAt=record.recorded_at,
        grade=record.grade,
        awarded=record.awarded_marks,
        maximum=record.maximum_marks,
        label=paper_code_label(record.metadata),
    )


def marks_to_win(records: list[PaperRecord]) -> dict[str, int]:
    """Mean marks lost per paper on each topic, over the papers that tested it.

    Grade-bearing papers only: "+N marks" is a claim in paper marks, and a
    quiz's marks are on a different scale (``docs/quiz-model.md`` §5). A topic
    that only ever appeared in quizzes is absent (callers read it as 0).
    """
    lost: dict[str, list[int]] = defaultdict(list)
    for record in records:
        if not is_grade_bearing(record):
            continue
        for area in record.weak_areas:
            lost[area.topic].append(area.lost_marks)
    return {topic: _half_up(sum(values) / len(values)) for topic, values in lost.items()}
