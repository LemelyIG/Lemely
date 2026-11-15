"""Unit tests for the pure builders behind ``GET /api/student/home``."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.exam_calendar_repo import ExamDateRow, StudentExamCalendar, StudentExamEntry
from lemely.db.models.enums import QuizSubmissionStatus, XpSource
from lemely.db.quiz_taking_repo import AssignedQuizRow
from lemely.db.student_home_repo import TeacherReplyRow
from lemely.db.study_plan_repo import SessionView
from lemely.db.xp_repo import StreakState, XpBreakdown
from lemely.io.det.profiles import get_profile
from lemely.web.schemas_student import UploadRunDTO
from lemely.web.schemas_student_home import TeacherReplyDTO, TodayDTO
from lemely.web.services.student_home import (
    HomeInputs,
    back_moment,
    build_activity,
    build_floor,
    build_goals,
    build_home,
    build_homework,
    build_recent_papers,
    build_stats,
    build_teacher_replies,
    build_today_sessions,
    build_week,
    build_win_back,
    focus_question,
    marking_moment,
    next_boundary,
    next_exam_on,
    paper_moment,
    question_label,
    streak_moments,
)

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
BOUNDARIES = {"A*": 90.0, "A": 80.0, "B": 70.0, "C": 60.0, "D": 50.0, "E": 40.0}


def _boundaries(_metadata: ExamMetadata) -> dict[str, float]:
    return dict(BOUNDARIES)


def _weak(topic: str, lost: int, maximum: int, qid: str) -> WeakArea:
    return WeakArea(
        topic=topic,
        lost_marks=lost,
        maximum_marks=maximum,
        accuracy=round(1.0 - lost / maximum, 4),
        question_ids=[qid],
    )


def _paper(
    *,
    code: str = "0580",
    paper: int = 4,
    awarded: int = 61,
    maximum: int = 80,
    grade: str = "B",
    at: datetime = NOW - timedelta(hours=2),
    weak: list[WeakArea] | None = None,
    origin: str = "past_paper",
    attempt_id: str | None = None,
) -> PaperRecord:
    return PaperRecord(
        student_id="s",
        metadata=ExamMetadata(
            subject_code=code,
            paper_number=paper,
            paper_variant=2,
            session_month="May/June",
            session_year=2024,
        ),
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=round(awarded / maximum * 100, 2),
        grade=grade,
        weak_areas=weak or [],
        recorded_at=at.isoformat(),
        origin=origin,  # type: ignore[arg-type]
        attempt_id=attempt_id,
    )


def test_next_boundary_returns_the_next_grade_and_rounded_up_points() -> None:
    assert next_boundary(76, BOUNDARIES) == ("A", 4)
    assert next_boundary(79.2, BOUNDARIES) == ("A", 1)
    assert next_boundary(95, BOUNDARIES) == (None, None)


def test_floor_grades_each_subject_from_its_weighted_mean() -> None:
    records = [
        _paper(code="0580", awarded=48, maximum=80, grade="C", at=NOW - timedelta(days=20)),
        _paper(code="0580", awarded=61, maximum=80, grade="B", at=NOW - timedelta(days=2)),
        _paper(code="0625", awarded=27, maximum=40, grade="C", at=NOW - timedelta(days=9)),
    ]
    floor = build_floor(records, _boundaries)
    assert [f.code for f in floor] == ["0580", "0625"]
    maths = floor[0]
    # (48 + 61) / 160 = 68% -> C, next B at 70 -> 2 points.
    assert (maths.grade, maths.nextGrade, maths.pointsToNext, maths.papers) == ("C", "B", 2, 2)
    # The grade before the latest paper: 48/80 = 60% -> C.
    assert maths.previousGrade == "C"
    assert maths.name == (get_profile("0580").name or "0580")
    physics = floor[1]
    assert physics.previousGrade is None


def test_floor_ignores_quiz_records() -> None:
    records = [_paper(origin="quiz", awarded=10, maximum=10, grade="A*")]
    assert build_floor(records, _boundaries) == []


def test_win_back_ranks_topics_from_each_subjects_latest_paper() -> None:
    records = [
        _paper(code="0580", at=NOW - timedelta(days=30), weak=[_weak("Old topic", 20, 30, "1")]),
        _paper(
            code="0580",
            at=NOW - timedelta(days=2),
            weak=[_weak("Vectors", 9, 12, "8"), _weak("Algebra", 0, 10, "2")],
        ),
        _paper(code="0625", at=NOW - timedelta(days=5), weak=[_weak("Waves", 7, 10, "3")]),
        _paper(code="0606", at=NOW - timedelta(days=6), weak=[_weak("Inequalities", 6, 9, "5")]),
        _paper(
            code="0606", at=NOW - timedelta(days=6), origin="quiz", weak=[_weak("Q", 50, 60, "9")]
        ),
    ]
    rows = build_win_back(records)
    assert [(r.topic, r.subjectCode, r.marks) for r in rows] == [
        ("Vectors", "0580", 9),
        ("Waves", "0625", 7),
        ("Inequalities", "0606", 6),
    ]


def test_recent_papers_are_newest_first_with_history_indices_as_ids() -> None:
    records = [
        _paper(code="0580", at=NOW - timedelta(days=9)),
        _paper(origin="quiz", at=NOW - timedelta(days=8)),
        _paper(code="0625", at=NOW - timedelta(days=1)),
    ]
    rows = build_recent_papers(records)
    assert [(r.paperId, r.subjectCode) for r in rows] == [("2", "0625"), ("0", "0580")]


def test_focus_question_picks_most_lost_or_easiest_win() -> None:
    record = _paper(weak=[_weak("Vectors", 9, 12, "8"), _weak("Units", 1, 10, "3")])
    assert focus_question(record, easiest=False) == "8"
    assert focus_question(record, easiest=True) == "3"
    assert focus_question(_paper(weak=[]), easiest=False) is None


def test_paper_moment_is_a_result_when_recent_and_not_a_drop() -> None:
    records = [
        _paper(grade="C", at=NOW - timedelta(days=20)),
        _paper(grade="B", awarded=61, weak=[_weak("Vectors", 9, 12, "8")]),
    ]
    moment = paper_moment(records, NOW)
    assert moment is not None
    assert (moment.kind, moment.grade, moment.previousGrade, moment.focusQuestion) == (
        "result",
        "B",
        "C",
        "8",
    )
    assert moment.paperId == "1"


def test_paper_moment_is_tough_for_a_low_grade_or_a_drop() -> None:
    low = paper_moment([_paper(grade="D", awarded=42)], NOW)
    assert low is not None
    assert low.kind == "tough"
    dropped = paper_moment([_paper(grade="A", at=NOW - timedelta(days=9)), _paper(grade="B")], NOW)
    assert dropped is not None
    assert dropped.kind == "tough"


def test_paper_moment_expires_after_48_hours() -> None:
    assert paper_moment([_paper(at=NOW - timedelta(hours=49))], NOW) is None
    assert paper_moment([], NOW) is None


def test_stats_count_papers_and_practice_marks() -> None:
    records = [
        _paper(grade="B"),
        _paper(code="0606", grade="A"),
        _paper(origin="quiz", awarded=7, maximum=9),
        _paper(origin="quiz", awarded=5, maximum=10),
    ]
    stats = build_stats(records)
    assert stats.papersMarked == 2
    assert stats.marksWonBack == 12
    assert stats.bestGrade is not None
    assert (stats.bestGrade.grade, stats.bestGrade.subjectCode) == ("A", "0606")
    assert build_stats([]).bestGrade is None


def test_activity_merges_papers_practice_and_teacher_replies_newest_first() -> None:
    reply = TeacherReplyDTO(
        reviewId="r1",
        teacherName="Ms. Hanna",
        questionId="7",
        subjectCode="0580",
        subjectName="Mathematics",
        paperNumber=4,
        marksAdded=1,
        paperId="0",
        resolvedAt=NOW - timedelta(hours=1),
    )
    records = [
        _paper(at=NOW - timedelta(days=2)),
        _paper(origin="quiz", awarded=8, maximum=10, at=NOW - timedelta(hours=3)),
    ]
    rows = build_activity(records, [reply])
    assert [r.kind for r in rows] == ["teacher", "practice", "paper"]
    assert rows[0].title == "Ms. Hanna checked Q7"
    assert rows[0].sub == "Mathematics · +1 mark"
    assert rows[1].sub.endswith("8 of 10")


def test_question_label_adds_q_once() -> None:
    assert question_label("7") == "Q7"
    assert question_label("Q4b") == "Q4b"


# ── time-derived builders ─────────────────────────────────────────────────

TODAY = date(2026, 11, 12)  # a Thursday
MONDAY = date(2026, 11, 9)


def _bd(**xp: int) -> XpBreakdown:
    by_source = dict.fromkeys(XpSource, 0)
    for name, amount in xp.items():
        by_source[XpSource[name]] = amount
    return XpBreakdown(total=sum(by_source.values()), by_source=by_source)


def _streak(current: int = 9, last: date | None = TODAY, freezes: int = 0) -> StreakState:
    return StreakState(
        current_length=current, longest_length=14, last_active_on=last, freezes_available=freezes
    )


def _session(day: date, topic: str, *, done: bool = False, code: str = "0580") -> SessionView:
    return SessionView(
        id=uuid.uuid4(),
        date=day,
        topic=topic,
        activity_type=None,  # type: ignore[arg-type]
        duration_minutes=10,
        focus="",
        completed_at=NOW if done else None,
        subject_code=code,
    )


def test_goals_read_todays_xp_by_source_and_this_weeks_papers() -> None:
    goals = build_goals(_bd(quiz_completed=20), _bd(paper_corrected=50))
    assert goals == TodayDTO(practice=True, flashcards=False, paperThisWeek=True)
    assert build_goals(_bd(study_session_completed=5), _bd()).practice is True


def test_week_marks_done_days_labels_and_today() -> None:
    sessions = [
        _session(MONDAY, "Vectors"),
        _session(MONDAY, "Second"),
        _session(date(2026, 11, 13), "Paper 4"),
    ]
    xp = {MONDAY: 10, date(2026, 11, 10): 5, date(2026, 11, 14): 30}
    week = build_week(MONDAY, TODAY, xp, sessions)
    assert len(week) == 7
    assert week[0].label == "Vectors"
    assert [d.done for d in week] == [True, True, False, False, False, False, False]
    assert [d.isToday for d in week].index(True) == 3
    assert week[4].label == "Paper 4"


def test_today_sessions_only_today() -> None:
    rows = build_today_sessions(
        [_session(TODAY, "Vectors", done=True), _session(MONDAY, "x")], TODAY
    )
    assert [(r.topic, r.done, r.minutes) for r in rows] == [("Vectors", True, 10)]


def test_streak_at_risk_needs_evening_a_gap_today_and_no_freeze() -> None:
    goals = TodayDTO(practice=False, flashcards=False, paperThisWeek=True)
    yesterday = date(2026, 11, 11)
    at_risk = streak_moments(_streak(last=yesterday), goals, TODAY, 18)
    assert [(m.kind, m.streakDays) for m in at_risk] == [("streakAtRisk", 9)]
    assert streak_moments(_streak(last=yesterday), goals, TODAY, 10) == []
    assert streak_moments(_streak(last=yesterday, freezes=1), goals, TODAY, 20) == []
    assert streak_moments(_streak(current=1, last=yesterday), goals, TODAY, 20) == []
    assert streak_moments(_streak(last=TODAY), goals, TODAY, 20) == []


def test_goal_done_when_all_three_goals_are_met() -> None:
    goals = TodayDTO(practice=True, flashcards=True, paperThisWeek=True)
    assert [m.kind for m in streak_moments(_streak(current=10), goals, TODAY, 20)] == ["goalDone"]


def test_back_after_break_from_three_days_away() -> None:
    back = back_moment(_streak(current=0, last=date(2026, 11, 6)), TODAY)
    assert back is not None
    assert back.daysAway == 6
    assert back_moment(_streak(last=date(2026, 11, 10)), TODAY) is None
    assert back_moment(_streak(last=None), TODAY) is None


def test_marking_moment_only_for_a_live_run() -> None:
    run = UploadRunDTO(
        paperId="p1", status="processing", filename="phys.pdf", startedAt=NOW, stale=False
    )
    moment = marking_moment(run)
    assert moment is not None
    assert (moment.paperId, moment.filename, moment.stale) == ("p1", "phys.pdf", False)
    done = UploadRunDTO(paperId="p1", status="complete", filename=None, startedAt=None, stale=False)
    assert marking_moment(done) is None
    assert marking_moment(None) is None


def test_next_exam_is_the_earliest_future_date() -> None:
    def row(day: date) -> ExamDateRow:
        return ExamDateRow(
            paper_variant="2",
            exam_date=day,
            starts_at_local=None,
            duration_minutes=None,
            source="t",
        )

    calendar = StudentExamCalendar(
        availability="ok",  # type: ignore[arg-type]
        entries=[
            StudentExamEntry(
                subject_code="0580",
                session_month=None,
                session_year=None,
                paper_number=4,
                availability="dated",  # type: ignore[arg-type]
                dates=[row(date(2026, 11, 1)), row(date(2027, 5, 10)), row(date(2027, 5, 3))],
            )
        ],
    )
    assert next_exam_on(calendar, TODAY) == date(2027, 5, 3)
    assert next_exam_on(StudentExamCalendar(availability="ok", entries=[]), TODAY) is None  # type: ignore[arg-type]


def _assigned(**overrides: object) -> AssignedQuizRow:
    base: dict[str, object] = {
        "assignment_id": uuid.uuid4(),
        "quiz_title": "Trigonometry set",
        "subject_code": "0580",
        "class_name": "10B",
        "teacher_name": "Ms. Hanna",
        "assigned_at": NOW - timedelta(days=1),
        "due_at": NOW + timedelta(days=2),
        "closes_at": None,
        "question_count": 12,
        "time_limit_minutes": None,
        "submission_status": QuizSubmissionStatus.not_started,
        "is_open": True,
        "is_overdue": False,
    }
    base.update(overrides)
    return AssignedQuizRow(**base)  # type: ignore[arg-type]


def test_homework_is_open_teacher_work_due_soonest_first() -> None:
    rows = [
        _assigned(quiz_title="Later", due_at=NOW + timedelta(days=5)),
        _assigned(quiz_title="Soon", due_at=NOW + timedelta(days=1)),
        _assigned(quiz_title="Mine", teacher_name=None),
        _assigned(quiz_title="Done", submission_status=QuizSubmissionStatus.submitted),
        _assigned(quiz_title="Closed", is_open=False),
        _assigned(quiz_title="No date", due_at=None),
    ]
    assert [h.title for h in build_homework(rows)] == ["Soon", "Later", "No date"]


def _inputs(**overrides: object) -> HomeInputs:
    base: dict[str, object] = {
        "student_name": "Mariam Adel",
        "records": [],
        "now": NOW,
        "local_date": TODAY,
        "local_hour": 15,
        "week_start": MONDAY,
        "streak": _streak(current=0, last=None),
        "today_xp": _bd(),
        "week_xp": _bd(),
        "week_xp_by_day": {},
        "sessions": [],
        "calendar": None,
        "assigned": [],
        "active_run": None,
        "teacher_replies": [],
        "class_count": 0,
    }
    base.update(overrides)
    return HomeInputs(**base)  # type: ignore[arg-type]


def test_build_home_for_a_new_student_is_neutral_and_never_needs_boundaries() -> None:
    def refuse(_metadata: ExamMetadata) -> dict[str, float]:
        raise AssertionError("no papers, no boundaries")

    home = build_home(_inputs(), refuse)
    assert home.moments == []
    assert home.floor == []
    assert home.stats.papersMarked == 0
    assert home.lastPaperAt is None
    assert len(home.week) == 7
    assert home.nextExamOn is None


def test_build_home_orders_moments_marking_paper_reply_streak_back() -> None:
    run = UploadRunDTO(paperId="u1", status="processing", filename=None, startedAt=NOW, stale=False)
    home = build_home(
        _inputs(
            records=[_paper(grade="B")],
            active_run=run,
            streak=_streak(current=0, last=date(2026, 11, 6)),
        ),
        _boundaries,
    )
    assert [m.kind for m in home.moments] == ["marking", "result", "backAfterBreak"]
    # 61/80 = 76% against BOUNDARIES -> B
    assert home.floor[0].grade == "B"


def test_teacher_replies_link_to_history_by_attempt_id_with_real_repo_rows() -> None:
    linked, unlinked = uuid.uuid4(), uuid.uuid4()

    def _row(attempt: uuid.UUID, name: str, code: str | None) -> TeacherReplyRow:
        return TeacherReplyRow(
            review_id=uuid.uuid4(),
            attempt_id=attempt,
            teacher_name=name,
            question_id="7",
            subject_code=code,
            paper_number=4 if code else None,
            marks_added=1,
            resolved_at=NOW - timedelta(hours=1),
        )

    records = [_paper(at=NOW - timedelta(days=3)), _paper(attempt_id=str(linked))]
    replies = build_teacher_replies(
        [_row(linked, "Ms. Hanna", "0580"), _row(unlinked, "Your teacher", None)],
        {str(linked): 1},
    )
    assert [r.paperId for r in replies] == ["1", None]
    assert (replies[0].teacherName, replies[0].subjectName, replies[0].marksAdded) == (
        "Ms. Hanna",
        "Mathematics",
        1,
    )
    assert (replies[1].subjectCode, replies[1].subjectName) == (None, None)
    home = build_home(
        _inputs(records=records, teacher_replies=[_row(linked, "Ms. Hanna", "0580")]), _boundaries
    )
    assert home.teacherReplies[0].paperId == "1"
