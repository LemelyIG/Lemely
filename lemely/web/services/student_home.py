"""Pure builders for ``GET /api/student/home`` (redesign lane L1).

Every function takes plain values and returns DTOs: no database, no clock, no
network. The router gathers inputs from the existing services and hands them
over, so each rule here is a unit test. Grades reuse the Overview's own rule
(:func:`lemely.web.routers.student._grade_for`, mark-weighted mean against the
latest paper's boundaries) so Home, Overview and Subject never disagree.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from lemely.core.history import is_grade_bearing
from lemely.io.det.profiles import get_profile
from lemely.web.routers.student import _grade_for
from lemely.web.schemas_student_home import (
    ActivityDTO,
    BestGradeDTO,
    FloorSubjectDTO,
    HomeStatsDTO,
    PaperMomentDTO,
    RecentPaperDTO,
    TeacherReplyDTO,
    WinBackTopicDTO,
)

if TYPE_CHECKING:
    from lemely.core.history import PaperRecord
    from lemely.core.schemas import ExamMetadata

BoundariesFor = Callable[["ExamMetadata"], dict[str, float]]

GRADE_ORDER: tuple[str, ...] = ("U", "G", "F", "E", "D", "C", "B", "A", "A*")
TOUGH_GRADES = frozenset({"D", "E", "F", "G", "U"})
RESULT_WINDOW = timedelta(hours=48)
REPLY_WINDOW = timedelta(days=7)


def grade_rank(grade: str) -> int:
    """Position on the grade ladder, ``-1`` for anything off it."""
    return GRADE_ORDER.index(grade) if grade in GRADE_ORDER else -1


def subject_name(code: str) -> str:
    """The subject's human name, falling back to its code (never invented)."""
    return get_profile(code).name or code


def question_label(question_id: str) -> str:
    """``"7"`` -> ``"Q7"``; an id that already starts with Q is left alone."""
    return question_id if question_id[:1] in {"Q", "q"} else f"Q{question_id}"


def recorded_at(record: PaperRecord) -> datetime:
    """The record's timestamp as an aware datetime."""
    moment = datetime.fromisoformat(record.recorded_at)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def indexed_papers(records: Sequence[PaperRecord]) -> list[tuple[int, PaperRecord]]:
    """Grade-bearing records paired with their index in the full history.

    The index is the id ``GET /student/result/{paper_id}`` addresses, the same
    scheme the Subject screen's paper history uses.
    """
    return [(i, r) for i, r in enumerate(records) if is_grade_bearing(r)]


def next_boundary(pct: float, boundaries: dict[str, float]) -> tuple[str | None, int | None]:
    """The next grade above ``pct`` and the whole percentage points to reach it."""
    above = sorted((threshold, grade) for grade, threshold in boundaries.items() if threshold > pct)
    if not above:
        return None, None
    threshold, grade = above[0]
    return grade, math.ceil(threshold - pct)


def _weighted_pct(records: Sequence[PaperRecord]) -> int:
    awarded = sum(r.awarded_marks for r in records)
    maximum = sum(r.maximum_marks for r in records)
    return round(awarded / maximum * 100.0) if maximum else 0


def build_floor(
    records: Sequence[PaperRecord], boundaries_for: BoundariesFor
) -> list[FloorSubjectDTO]:
    """One grade per subject, plus the gap to the next grade."""
    by_code: dict[str, list[PaperRecord]] = {}
    for _, record in indexed_papers(records):
        by_code.setdefault(record.metadata.subject_code, []).append(record)
    floor: list[FloorSubjectDTO] = []
    for code, papers in sorted(by_code.items()):
        boundaries = boundaries_for(papers[-1].metadata)
        pct = _weighted_pct(papers)
        previous = (
            _grade_for(float(_weighted_pct(papers[:-1])), boundaries) if len(papers) > 1 else None
        )
        next_grade, points = next_boundary(pct, boundaries)
        floor.append(
            FloorSubjectDTO(
                code=code,
                name=subject_name(code),
                grade=_grade_for(float(pct), boundaries),
                previousGrade=previous,
                nextGrade=next_grade,
                pointsToNext=points,
                papers=len(papers),
            )
        )
    return floor


def build_win_back(records: Sequence[PaperRecord], *, limit: int = 3) -> list[WinBackTopicDTO]:
    """Topics that cost marks on each subject's latest paper, biggest first."""
    latest: dict[str, PaperRecord] = {}
    for _, record in indexed_papers(records):
        latest[record.metadata.subject_code] = record
    topics = [
        WinBackTopicDTO(
            topic=area.topic,
            subjectCode=code,
            subjectName=subject_name(code),
            marks=area.lost_marks,
        )
        for code, record in latest.items()
        for area in record.weak_areas
        if area.lost_marks > 0
    ]
    topics.sort(key=lambda t: (-t.marks, t.topic))
    return topics[:limit]


def build_recent_papers(records: Sequence[PaperRecord], *, limit: int = 3) -> list[RecentPaperDTO]:
    """The newest grade-bearing papers."""
    rows = [
        RecentPaperDTO(
            paperId=str(index),
            subjectCode=record.metadata.subject_code,
            subjectName=subject_name(record.metadata.subject_code),
            paperNumber=record.metadata.paper_number,
            awarded=record.awarded_marks,
            maximum=record.maximum_marks,
            grade=record.grade,
            recordedAt=recorded_at(record),
        )
        for index, record in reversed(indexed_papers(records))
    ]
    return rows[:limit]


def focus_question(record: PaperRecord, *, easiest: bool) -> str | None:
    """The question Binny points at: the biggest loss, or the easiest win back."""
    lost = [a for a in record.weak_areas if a.lost_marks > 0 and a.question_ids]
    if not lost:
        return None
    pick = max(lost, key=lambda a: a.accuracy) if easiest else max(lost, key=lambda a: a.lost_marks)
    return pick.question_ids[0]


def paper_moment(records: Sequence[PaperRecord], now: datetime) -> PaperMomentDTO | None:
    """A ``result`` or ``tough`` moment for a paper marked in the last 48 hours."""
    papers = indexed_papers(records)
    if not papers:
        return None
    index, last = papers[-1]
    if now - recorded_at(last) > RESULT_WINDOW:
        return None
    code = last.metadata.subject_code
    earlier = [r for _, r in papers[:-1] if r.metadata.subject_code == code]
    previous = earlier[-1].grade if earlier else None
    dropped = previous is not None and grade_rank(last.grade) < grade_rank(previous)
    tough = last.grade in TOUGH_GRADES or dropped
    return PaperMomentDTO(
        kind="tough" if tough else "result",
        paperId=str(index),
        subjectCode=code,
        subjectName=subject_name(code),
        paperNumber=last.metadata.paper_number,
        awarded=last.awarded_marks,
        maximum=last.maximum_marks,
        grade=last.grade,
        previousGrade=previous,
        focusQuestion=focus_question(last, easiest=tough),
        recordedAt=recorded_at(last),
    )


def build_stats(records: Sequence[PaperRecord]) -> HomeStatsDTO:
    """Me's three stats: papers marked, practice marks won, best paper grade."""
    papers = [r for _, r in indexed_papers(records)]
    practice = [r for r in records if not is_grade_bearing(r)]
    ranked = [r for r in papers if grade_rank(r.grade) >= 0]
    best = max(ranked, key=lambda r: grade_rank(r.grade), default=None)
    return HomeStatsDTO(
        papersMarked=len(papers),
        marksWonBack=sum(r.awarded_marks for r in practice),
        bestGrade=(
            BestGradeDTO(grade=best.grade, subjectCode=best.metadata.subject_code)
            if best is not None
            else None
        ),
    )


def attempt_index(records: Sequence[PaperRecord]) -> dict[str, int]:
    """``attempts.id`` -> history index, for linking a teacher reply to its result."""
    return {r.attempt_id: i for i, r in enumerate(records) if r.attempt_id}


def build_activity(
    records: Sequence[PaperRecord], replies: Sequence[TeacherReplyDTO], *, limit: int = 6
) -> list[ActivityDTO]:
    """Me's recent-activity timeline, newest first."""
    events: list[ActivityDTO] = []
    for record in records:
        name = subject_name(record.metadata.subject_code)
        if is_grade_bearing(record):
            events.append(
                ActivityDTO(
                    kind="paper",
                    title="Paper marked",
                    sub=f"{name} P{record.metadata.paper_number} · {record.grade}",
                    at=recorded_at(record),
                )
            )
        else:
            events.append(
                ActivityDTO(
                    kind="practice",
                    title="Practice done",
                    sub=f"{name} · {record.awarded_marks} of {record.maximum_marks}",
                    at=recorded_at(record),
                )
            )
    for reply in replies:
        plural = "" if reply.marksAdded == 1 else "s"
        added = f" · +{reply.marksAdded} mark{plural}" if reply.marksAdded else ""
        events.append(
            ActivityDTO(
                kind="teacher",
                title=f"{reply.teacherName} checked {question_label(reply.questionId)}",
                sub=f"{reply.subjectName or 'Your paper'}{added}",
                at=reply.resolvedAt,
            )
        )
    events.sort(key=lambda e: e.at, reverse=True)
    return events[:limit]
