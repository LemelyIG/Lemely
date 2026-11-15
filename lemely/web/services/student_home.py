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
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from lemely.core.history import is_grade_bearing
from lemely.db.models.enums import QuizSubmissionStatus, XpSource
from lemely.io.det.profiles import get_profile
from lemely.web.routers.student import _grade_for
from lemely.web.schemas_student_home import (
    ActivityDTO,
    BackMomentDTO,
    BestGradeDTO,
    FloorSubjectDTO,
    HomeStatsDTO,
    HomeworkDTO,
    MarkingMomentDTO,
    MomentDTO,
    PaperMomentDTO,
    PlanSessionDTO,
    RecentPaperDTO,
    StreakDTO,
    StreakMomentDTO,
    StudentHomeDTO,
    TeacherReplyDTO,
    TeacherReplyMomentDTO,
    TodayDTO,
    WeekDayDTO,
    WinBackTopicDTO,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from lemely.core.history import PaperRecord
    from lemely.core.schemas import ExamMetadata
    from lemely.db.exam_calendar_repo import StudentExamCalendar
    from lemely.db.quiz_taking_repo import AssignedQuizRow
    from lemely.db.student_home_repo import TeacherReplyRow
    from lemely.db.study_plan_repo import SessionView
    from lemely.db.xp_repo import StreakState, XpBreakdown
    from lemely.web.schemas_student import UploadRunDTO

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


BREAK_DAYS = 3
STREAK_RISK_HOUR = 17
_OPEN_SUBMISSION = frozenset({QuizSubmissionStatus.not_started, QuizSubmissionStatus.in_progress})
_LIVE_RUN = frozenset({"pending", "processing"})


def build_goals(today: XpBreakdown, week: XpBreakdown) -> TodayDTO:
    """Today's three goals from XP already earned: practice, flashcards, a paper this week."""
    practice = (
        today.by_source.get(XpSource.quiz_completed, 0) > 0
        or today.by_source.get(XpSource.study_session_completed, 0) > 0
    )
    return TodayDTO(
        practice=practice,
        flashcards=today.by_source.get(XpSource.flashcard_reviewed, 0) > 0,
        paperThisWeek=week.by_source.get(XpSource.paper_corrected, 0) > 0,
    )


def build_today_sessions(sessions: Iterable[SessionView], local_date: date) -> list[PlanSessionDTO]:
    """Study-plan sessions scheduled for today, across subjects."""
    return [
        PlanSessionDTO(
            sessionId=str(s.id),
            subjectCode=s.subject_code,
            topic=s.topic,
            minutes=s.duration_minutes,
            done=s.completed_at is not None,
        )
        for s in sessions
        if s.date == local_date
    ]


def build_week(
    week_start: date,
    local_date: date,
    xp_by_day: dict[date, int],
    sessions: Sequence[SessionView],
) -> list[WeekDayDTO]:
    """Mon-Sun: a day is done when it earned XP; its label is its first planned topic."""
    labels: dict[date, str] = {}
    for session in sorted(sessions, key=lambda s: s.date):
        labels.setdefault(session.date, session.topic)
    days: list[WeekDayDTO] = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        days.append(
            WeekDayDTO(
                day=day,
                label=labels.get(day),
                done=day <= local_date and xp_by_day.get(day, 0) > 0,
                isToday=day == local_date,
            )
        )
    return days


def streak_dto(streak: StreakState) -> StreakDTO:
    return StreakDTO(
        current=streak.current_length,
        longest=streak.longest_length,
        lastActiveOn=streak.last_active_on,
        freezesAvailable=streak.freezes_available,
    )


def streak_moments(
    streak: StreakState, goals: TodayDTO, local_date: date, local_hour: int
) -> list[StreakMomentDTO]:
    """``goalDone`` when all three goals are met, else ``streakAtRisk`` when it applies.

    At risk means: a streak of two days or more, last active yesterday, nothing
    earned yet today, it is evening in the student's own zone, and no freeze is
    saved. A saved freeze covers the day on its own, so warning about it would
    be the leverage the Profile screen promised never to use.
    """
    if goals.practice and goals.flashcards and goals.paperThisWeek:
        return [StreakMomentDTO(kind="goalDone", streakDays=streak.current_length)]
    at_risk = (
        streak.current_length >= 2
        and streak.freezes_available == 0
        and streak.last_active_on == local_date - timedelta(days=1)
        and local_hour >= STREAK_RISK_HOUR
    )
    if at_risk:
        return [StreakMomentDTO(kind="streakAtRisk", streakDays=streak.current_length)]
    return []


def back_moment(streak: StreakState, local_date: date) -> BackMomentDTO | None:
    """Back after a break: three or more days since the last XP."""
    if streak.last_active_on is None:
        return None
    away = (local_date - streak.last_active_on).days
    return BackMomentDTO(daysAway=away) if away >= BREAK_DAYS else None


def marking_moment(run: UploadRunDTO | None) -> MarkingMomentDTO | None:
    """A paper is being marked right now."""
    if run is None or run.status not in _LIVE_RUN:
        return None
    return MarkingMomentDTO(
        paperId=run.paperId, filename=run.filename, startedAt=run.startedAt, stale=run.stale
    )


def next_exam_on(calendar: StudentExamCalendar, local_date: date) -> date | None:
    """The earliest exam date still ahead, across every declared paper and variant."""
    upcoming = [
        row.exam_date
        for entry in calendar.entries
        for row in entry.dates
        if row.exam_date >= local_date
    ]
    return min(upcoming, default=None)


def build_homework(rows: Sequence[AssignedQuizRow], *, limit: int = 3) -> list[HomeworkDTO]:
    """Open, unsubmitted work a teacher set, due soonest first."""
    open_rows = [
        r
        for r in rows
        if r.teacher_name is not None and r.is_open and r.submission_status in _OPEN_SUBMISSION
    ]
    far = datetime.max.replace(tzinfo=UTC)
    open_rows.sort(key=lambda r: (r.due_at or far, r.assigned_at))
    return [
        HomeworkDTO(
            assignmentId=str(r.assignment_id),
            title=r.quiz_title,
            subjectCode=r.subject_code,
            teacherName=r.teacher_name or "",
            dueAt=r.due_at,
            questionCount=r.question_count,
            isOverdue=r.is_overdue,
        )
        for r in open_rows[:limit]
    ]


def build_teacher_replies(
    rows: Sequence[TeacherReplyRow], index: dict[str, int]
) -> list[TeacherReplyDTO]:
    """Teacher replies, each linked to its result when the paper is in history."""
    return [
        TeacherReplyDTO(
            reviewId=str(row.review_id),
            teacherName=row.teacher_name,
            questionId=row.question_id,
            subjectCode=row.subject_code,
            subjectName=subject_name(row.subject_code) if row.subject_code else None,
            paperNumber=row.paper_number,
            marksAdded=row.marks_added,
            paperId=str(index[str(row.attempt_id)]) if str(row.attempt_id) in index else None,
            resolvedAt=row.resolved_at,
        )
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class HomeInputs:
    """Everything the router gathered for one request."""

    student_name: str
    records: Sequence[PaperRecord]
    now: datetime
    local_date: date
    local_hour: int
    week_start: date
    streak: StreakState
    today_xp: XpBreakdown
    week_xp: XpBreakdown
    week_xp_by_day: dict[date, int]
    sessions: Sequence[SessionView]
    calendar: StudentExamCalendar | None
    assigned: Sequence[AssignedQuizRow]
    active_run: UploadRunDTO | None
    teacher_replies: Sequence[TeacherReplyRow]
    class_count: int


def build_home(inputs: HomeInputs, boundaries_for: BoundariesFor) -> StudentHomeDTO:
    """Assemble the whole payload. The client picks the stage moment from ``moments``."""
    records = inputs.records
    papers = indexed_papers(records)
    replies = build_teacher_replies(inputs.teacher_replies, attempt_index(records))
    goals = build_goals(inputs.today_xp, inputs.week_xp)

    moments: list[MomentDTO] = []
    marking = marking_moment(inputs.active_run)
    if marking is not None:
        moments.append(marking)
    paper = paper_moment(records, inputs.now)
    if paper is not None:
        moments.append(paper)
    if replies:
        moments.append(TeacherReplyMomentDTO(reply=replies[0]))
    moments.extend(streak_moments(inputs.streak, goals, inputs.local_date, inputs.local_hour))
    back = back_moment(inputs.streak, inputs.local_date)
    if back is not None:
        moments.append(back)

    return StudentHomeDTO(
        studentName=inputs.student_name,
        localDate=inputs.local_date,
        localHour=inputs.local_hour,
        moments=moments,
        goals=goals,
        todaySessions=build_today_sessions(inputs.sessions, inputs.local_date),
        week=build_week(
            inputs.week_start, inputs.local_date, inputs.week_xp_by_day, inputs.sessions
        ),
        streak=streak_dto(inputs.streak),
        nextExamOn=next_exam_on(inputs.calendar, inputs.local_date) if inputs.calendar else None,
        floor=build_floor(records, boundaries_for) if papers else [],
        winBack=build_win_back(records),
        recentPapers=build_recent_papers(records),
        lastPaperAt=recorded_at(papers[-1][1]) if papers else None,
        teacherReplies=replies,
        homework=build_homework(inputs.assigned),
        classCount=inputs.class_count,
        stats=build_stats(records),
        activity=build_activity(records, replies),
    )
