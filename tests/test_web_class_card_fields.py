"""``GET /api/teacher/classes`` class-card fields: grade, delta, lastPaper, topWeaknessAccuracy.

The teacher home's class cards show a median grade chip, a trend line
("+0.4 · P4 · today") and the weak topic's accuracy. These pin the field
definitions on ``ClassSummaryDTO`` (all additive, ``None`` when the data
does not exist, never a placeholder):

- ``grade``: median of each student's latest grade-bearing paper grade, in
  CAIE order; an even count takes the lower of the two middle grades.
- ``delta``: mean of the latest papers minus mean of the previous papers, over
  students with two grade-bearing papers in the latest paper's subject.
- ``lastPaper``: ``"P<n>"`` of the class's most recent grade-bearing paper.
- ``topWeakness`` / ``topWeaknessAccuracy``: the worst topic over each
  student's latest grade-bearing paper, and its marks earned / marks
  available across those same papers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from lemely.core.history import PaperOrigin, PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.routers.classes import _class_card_trend, _median_grade
from tests.test_web_classes import (
    _seed_user,
    class_service,  # noqa: F401
    client,  # noqa: F401
    history_store,  # noqa: F401
    pg_sessionmaker,  # noqa: F401
    settings,  # noqa: F401
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.history import StudentHistory
    from lemely.db.class_repo import ClassService
    from lemely.io.history_store import HistoryStore


def _record(
    student_id: uuid.UUID | str,
    *,
    percentage: float,
    grade: str,
    days_ago: int,
    paper_number: int = 4,
    subject_code: str = "0625",
    origin: PaperOrigin = "past_paper",
    weak: dict[str, float] | None = None,
) -> PaperRecord:
    """One history record; ``weak`` maps topic -> accuracy (lost marks derived)."""
    areas = [
        WeakArea(
            topic=topic,
            lost_marks=round((1 - accuracy) * 10),
            maximum_marks=10,
            accuracy=accuracy,
            question_ids=["1"],
        )
        for topic, accuracy in (weak or {}).items()
    ]
    return PaperRecord(
        student_id=str(student_id),
        metadata=ExamMetadata(
            subject_code=subject_code,
            paper_number=paper_number,
            paper_variant=1,
            session_month="May/June",
            session_year=2020,
        ),
        awarded_marks=int(percentage),
        maximum_marks=100,
        percentage=percentage,
        grade=grade,
        weak_areas=areas,
        recorded_at=(datetime.now(UTC) - timedelta(days=days_ago)).isoformat(),
        origin=origin,
    )


def _summary(api: TestClient, teacher: uuid.UUID) -> dict[str, object]:
    api.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id=str(teacher), role=Role.teacher.value
    )
    classes = api.get("/api/teacher/classes").json()["classes"]
    assert len(classes) == 1
    return classes[0]  # type: ignore[no-any-return]


def _enrol(
    sm: sessionmaker[Session], service: ClassService, teacher: uuid.UUID, count: int
) -> list[uuid.UUID]:
    cls = service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    students = [_seed_user(sm, Role.student, display_name=f"S{i}") for i in range(count)]
    for student in students:
        service.join_by_code(student, cls.join_code)
    return students


# ---------------------------------------------------------------------------
# Pure helpers.
# ---------------------------------------------------------------------------


def test_median_grade_odd_count_is_the_middle_grade() -> None:
    assert _median_grade(["U", "A*", "B"]) == "B"


def test_median_grade_tie_takes_the_lower_middle_grade() -> None:
    # Ordered best first: A, B, C, D. Middles B and C: the conservative one is C.
    assert _median_grade(["D", "A", "C", "B"]) == "C"


def test_median_grade_of_nothing_is_none() -> None:
    assert _median_grade([]) is None


def test_median_grade_orders_core_tier_grades_f_and_g() -> None:
    # IGCSE Core papers award F and G; they sit between E and U on the ladder.
    assert _median_grade(["G", "C", "F"]) == "F"
    assert _median_grade(["U", "G", "A*"]) == "G"
    assert _median_grade(["E", "F", "G", "U"]) == "G"


def test_median_grade_skips_grades_off_the_ladder() -> None:
    assert _median_grade(["B", "X", "C"]) == "C"
    assert _median_grade(["?"]) is None


def _history(*records: PaperRecord) -> StudentHistory:
    from lemely.core.history import StudentHistory

    return StudentHistory(student_id=records[0].student_id, records=list(records))


def test_trend_single_paper_has_no_delta() -> None:
    sid = str(uuid.uuid4())
    only = _record(sid, percentage=60, grade="C", days_ago=1)
    trend = _class_card_trend([_history(only)])
    assert trend.grade == "C"
    assert trend.delta is None
    assert trend.last_paper == "P4"
    assert trend.last_paper_at == only.recorded_at


def test_trend_delta_uses_only_students_with_two_papers() -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    histories = [
        _history(
            _record(a, percentage=50, grade="D", days_ago=5),
            _record(a, percentage=60, grade="C", days_ago=1),
        ),
        _history(
            _record(b, percentage=70, grade="B", days_ago=4),
            _record(b, percentage=75, grade="B", days_ago=2),
        ),
        _history(_record(str(uuid.uuid4()), percentage=10, grade="U", days_ago=1)),
    ]
    trend = _class_card_trend(histories)
    # (60 + 75) / 2 - (50 + 70) / 2 = 7.5
    assert trend.delta == 7.5


def test_trend_previous_paper_must_share_the_latest_subject() -> None:
    a = str(uuid.uuid4())
    histories = [
        _history(
            _record(a, percentage=20, grade="U", days_ago=5, subject_code="0580"),
            _record(a, percentage=60, grade="C", days_ago=1),
        )
    ]
    assert _class_card_trend(histories).delta is None


def test_trend_ignores_quizzes_for_grade_delta_and_last_paper() -> None:
    a = str(uuid.uuid4())
    paper = _record(a, percentage=40, grade="E", days_ago=5, paper_number=2)
    paper_at = paper.recorded_at
    histories = [
        _history(
            paper,
            _record(a, percentage=99, grade="A*", days_ago=1, paper_number=6, origin="quiz"),
        )
    ]
    trend = _class_card_trend(histories)
    assert trend.grade == "E"
    assert trend.delta is None
    assert trend.last_paper == "P2"
    assert trend.last_paper_at == paper_at


def test_trend_last_paper_is_the_class_wide_most_recent_paper() -> None:
    histories = [
        _history(_record(str(uuid.uuid4()), percentage=60, grade="C", days_ago=3, paper_number=2)),
        _history(_record(str(uuid.uuid4()), percentage=60, grade="C", days_ago=1, paper_number=6)),
    ]
    assert _class_card_trend(histories).last_paper == "P6"


def test_trend_weakness_accuracy_is_marks_weighted_over_latest_papers() -> None:
    histories = [
        _history(
            _record(str(uuid.uuid4()), percentage=60, grade="C", days_ago=1, weak={"Waves": 0.2})
        ),
        _history(
            _record(str(uuid.uuid4()), percentage=60, grade="C", days_ago=1, weak={"Waves": 0.6})
        ),
        _history(
            _record(str(uuid.uuid4()), percentage=60, grade="C", days_ago=1, weak={"Optics": 0.9})
        ),
    ]
    trend = _class_card_trend(histories)
    assert trend.top_weakness == "Waves"  # 8 + 4 marks lost beats Optics' 1
    assert trend.top_weakness_accuracy == 0.4  # (2 + 6) / (10 + 10)


def _weak(topic: str, lost: int, maximum: int) -> WeakArea:
    return WeakArea(
        topic=topic,
        lost_marks=lost,
        maximum_marks=maximum,
        accuracy=1 - lost / maximum,
        question_ids=["1"],
    )


def test_trend_weakness_accuracy_weights_by_maximum_marks() -> None:
    small = _record(str(uuid.uuid4()), percentage=60, grade="C", days_ago=1)
    small.weak_areas.append(_weak("Waves", 9, 10))  # 10% on 10 marks
    big = _record(str(uuid.uuid4()), percentage=60, grade="C", days_ago=1)
    big.weak_areas.append(_weak("Waves", 2, 40))  # 95% on 40 marks
    trend = _class_card_trend([_history(small), _history(big)])
    # Marks-weighted (1 + 38) / 50, not the mean of ratios (0.1 + 0.95) / 2.
    assert trend.top_weakness_accuracy == 0.78


def test_trend_weak_topic_and_accuracy_share_the_latest_paper_population() -> None:
    a = str(uuid.uuid4())
    histories = [
        _history(
            # An old paper and a newer quiz both lose heavily on Optics...
            _record(a, percentage=20, grade="U", days_ago=9, weak={"Optics": 0.0}),
            _record(a, percentage=60, grade="C", days_ago=3, weak={"Waves": 0.5}),
            _record(a, percentage=10, grade="U", days_ago=1, origin="quiz", weak={"Optics": 0.0}),
        )
    ]
    trend = _class_card_trend(histories)
    # ...but the latest paper lists Waves, so topic and accuracy both say Waves.
    assert trend.top_weakness == "Waves"
    assert trend.top_weakness_accuracy == 0.5


def test_trend_with_no_weak_topics_reports_no_weakness() -> None:
    trend = _class_card_trend(
        [_history(_record(str(uuid.uuid4()), percentage=90, grade="A", days_ago=1))]
    )
    assert (trend.top_weakness, trend.top_weakness_accuracy) == (None, None)


def test_trend_with_no_graded_papers_is_all_none() -> None:
    trend = _class_card_trend(
        [
            _history(
                _record(
                    str(uuid.uuid4()),
                    percentage=90,
                    grade="A",
                    days_ago=1,
                    origin="quiz",
                    weak={"Waves": 0.2},
                )
            )
        ],
    )
    assert (
        trend.grade,
        trend.delta,
        trend.last_paper,
        trend.top_weakness,
        trend.top_weakness_accuracy,
    ) == (None, None, None, None, None)


# ---------------------------------------------------------------------------
# Through the route.
# ---------------------------------------------------------------------------


def test_route_empty_class_reports_null_card_fields(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    class_service: ClassService,  # noqa: F811
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _enrol(pg_sessionmaker, class_service, teacher, 0)
    summary = _summary(client, teacher)
    assert summary["grade"] is None
    assert summary["delta"] is None
    assert summary["lastPaper"] is None
    assert summary["topWeaknessAccuracy"] is None


def test_route_multi_student_card_fields(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    class_service: ClassService,  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    a, b, quiz_only = _enrol(pg_sessionmaker, class_service, teacher, 3)
    history_store.append(str(a), _record(a, percentage=50, grade="D", days_ago=6))
    history_store.append(
        str(a), _record(a, percentage=62, grade="C", days_ago=2, weak={"Waves": 0.3})
    )
    history_store.append(
        str(b),
        _record(b, percentage=80, grade="A", days_ago=1, paper_number=6, weak={"Waves": 0.5}),
    )
    history_store.append(
        str(quiz_only),
        _record(quiz_only, percentage=100, grade="A*", days_ago=0, origin="quiz"),
    )
    summary = _summary(client, teacher)
    # Grades A, C: even count, the lower middle is C.
    assert summary["grade"] == "C"
    assert summary["delta"] == 12.0  # only ``a`` has two papers: 62 - 50
    assert summary["lastPaper"] == "P6"  # ``b``'s paper; the newer quiz is skipped
    assert summary["topWeakness"] == "Waves"
    assert summary["topWeaknessAccuracy"] == 0.4


def test_route_card_fields_scope_to_the_callers_own_class(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    class_service: ClassService,  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    mine = _seed_user(pg_sessionmaker, Role.teacher)
    theirs = _seed_user(pg_sessionmaker, Role.teacher)
    (my_student,) = _enrol(pg_sessionmaker, class_service, mine, 1)
    (their_student,) = _enrol(pg_sessionmaker, class_service, theirs, 1)
    history_store.append(
        str(my_student), _record(my_student, percentage=60, grade="C", days_ago=1, paper_number=2)
    )
    history_store.append(
        str(their_student),
        _record(their_student, percentage=95, grade="A*", days_ago=0, paper_number=6),
    )
    summary = _summary(client, mine)
    assert summary["grade"] == "C"
    assert summary["lastPaper"] == "P2"


def test_route_core_tier_grades_do_not_break_the_class_list(
    client: TestClient,  # noqa: F811
    pg_sessionmaker: sessionmaker[Session],  # noqa: F811
    class_service: ClassService,  # noqa: F811
    history_store: HistoryStore,  # noqa: F811
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    f_student, g_student, odd_student = _enrol(pg_sessionmaker, class_service, teacher, 3)
    history_store.append(str(f_student), _record(f_student, percentage=30, grade="F", days_ago=2))
    history_store.append(str(g_student), _record(g_student, percentage=20, grade="G", days_ago=1))
    history_store.append(
        str(odd_student), _record(odd_student, percentage=50, grade="Q", days_ago=1)
    )
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id=str(teacher), role=Role.teacher.value
    )
    response = client.get("/api/teacher/classes")
    assert response.status_code == 200
    assert len(response.json()["classes"]) == 1
