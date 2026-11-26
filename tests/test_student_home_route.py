"""``GET /api/student/home`` wiring, with every service faked."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.models.enums import UploadStatus, XpSource
from lemely.db.student_home_repo import TeacherReplyRow
from lemely.db.xp_repo import StreakState, XpBreakdown
from lemely.io.history_store import HistoryStore
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_class_service,
    get_exam_calendar_service,
    get_history_store,
    get_quiz_taking_service,
    get_student_profile_service,
    get_student_upload_repo,
    get_study_plan_service,
    get_user_mirror,
    get_user_zone_reader,
    get_xp_service,
)
from lemely.web.routers.student_home import get_student_home_reads

if TYPE_CHECKING:
    from pathlib import Path

STUDENT = uuid.uuid4()
NOW = datetime(2026, 11, 12, 16, 0, tzinfo=UTC)  # 18:00 in Cairo


class _Boundaries:
    def __init__(self) -> None:
        pass

    def resolve(self, _metadata: ExamMetadata) -> tuple[dict[str, float], str]:
        return {"A*": 90.0, "A": 80.0, "B": 70.0, "C": 60.0, "D": 50.0, "E": 40.0}, "exact"


def _breakdown(**xp: int) -> XpBreakdown:
    by_source = dict.fromkeys(XpSource, 0)
    for name, amount in xp.items():
        by_source[XpSource[name]] = amount
    return XpBreakdown(total=sum(by_source.values()), by_source=by_source)


def _record(*, at: datetime, grade: str = "B", attempt_id: str | None = None) -> PaperRecord:
    return PaperRecord(
        student_id=str(STUDENT),
        metadata=ExamMetadata(
            subject_code="0580",
            paper_number=4,
            paper_variant=2,
            session_month="May/June",
            session_year=2024,
        ),
        awarded_marks=61,
        maximum_marks=80,
        percentage=76.25,
        grade=grade,
        weak_areas=[
            WeakArea(
                topic="Vectors", lost_marks=9, maximum_marks=12, accuracy=0.25, question_ids=["8"]
            )
        ],
        recorded_at=at.isoformat(),
        attempt_id=attempt_id,
    )


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    monkeypatch.setattr("lemely.web.routers.student_home._now", lambda: NOW)
    monkeypatch.setattr("lemely.web.routers.student_home.GradeBoundaryStore", _Boundaries)
    xp = MagicMock()
    xp.streak.return_value = StreakState(
        current_length=9, longest_length=14, last_active_on=date(2026, 11, 11), freezes_available=0
    )
    xp.xp_breakdown.return_value = _breakdown()
    xp.xp_by_day.return_value = {}
    zones = MagicMock()
    zones.zone_for.return_value = ZoneInfo("Africa/Cairo")
    plans = MagicMock()
    plans.get_current.return_value = None
    calendar = MagicMock()
    calendar.calendar_for_student.return_value = MagicMock(entries=[])
    quizzes = MagicMock()
    quizzes.list_assigned.return_value = []
    uploads = MagicMock()
    uploads.get_active_run.return_value = None
    classes = MagicMock()
    classes.enrolled_class_ids.return_value = [uuid.uuid4()]
    reads = MagicMock()
    reads.recent_teacher_replies.return_value = []
    mirror = MagicMock()
    mirror.get_by_id.return_value = MagicMock(display_name="Mariam Adel", email="m@example.com")
    profiles = MagicMock()
    profiles.list_enrolments.return_value = []
    return {
        "xp": xp,
        "zones": zones,
        "plans": plans,
        "calendar": calendar,
        "quizzes": quizzes,
        "uploads": uploads,
        "classes": classes,
        "reads": reads,
        "mirror": mirror,
        "profiles": profiles,
    }


def _client(
    store: HistoryStore, fakes: dict[str, MagicMock], user_id: str = str(STUDENT)
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=user_id, role="student"
    )
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_xp_service] = lambda: fakes["xp"]
    app.dependency_overrides[get_user_zone_reader] = lambda: fakes["zones"]
    app.dependency_overrides[get_study_plan_service] = lambda: fakes["plans"]
    app.dependency_overrides[get_exam_calendar_service] = lambda: fakes["calendar"]
    app.dependency_overrides[get_quiz_taking_service] = lambda: fakes["quizzes"]
    app.dependency_overrides[get_student_upload_repo] = lambda: fakes["uploads"]
    app.dependency_overrides[get_class_service] = lambda: fakes["classes"]
    app.dependency_overrides[get_student_home_reads] = lambda: fakes["reads"]
    app.dependency_overrides[get_user_mirror] = lambda: fakes["mirror"]
    app.dependency_overrides[get_student_profile_service] = lambda: fakes["profiles"]
    return TestClient(app)


def test_home_for_a_student_with_a_fresh_paper(tmp_path: Path, fakes: dict[str, MagicMock]) -> None:
    store = HistoryStore(tmp_path / "h")
    store.append(str(STUDENT), _record(at=NOW - timedelta(hours=3), attempt_id="att-1"))
    fakes["reads"].recent_teacher_replies.return_value = [
        TeacherReplyRow(
            review_id=uuid.uuid4(),
            attempt_id=uuid.UUID(int=1),
            teacher_name="Ms. Hanna",
            question_id="7",
            subject_code="0580",
            paper_number=4,
            marks_added=1,
            resolved_at=NOW - timedelta(hours=1),
        )
    ]
    body = _client(store, fakes).get("/api/student/home").json()

    assert body["studentName"] == "Mariam Adel"
    assert body["localDate"] == "2026-11-12"
    assert body["localHour"] == 18
    kinds = [m["kind"] for m in body["moments"]]
    assert kinds == ["result", "teacherReply", "streakAtRisk"]
    assert body["moments"][0]["focusQuestion"] == "8"
    assert body["floor"][0] | {"name": None} == {
        "code": "0580",
        "name": None,
        "grade": "B",
        "previousGrade": None,
        "nextGrade": "A",
        "pointsToNext": 4,
        "papers": 1,
    }
    assert body["winBack"][0]["topic"] == "Vectors"
    assert body["recentPapers"][0]["paperId"] == "0"
    assert body["classCount"] == 1
    assert len(body["week"]) == 7
    fakes["reads"].recent_teacher_replies.assert_called_once()
    assert fakes["reads"].recent_teacher_replies.call_args.args[0] == STUDENT


def test_home_reads_only_the_callers_own_data(tmp_path: Path, fakes: dict[str, MagicMock]) -> None:
    _client(HistoryStore(tmp_path / "h"), fakes).get("/api/student/home")
    fakes["xp"].streak.assert_called_once()
    assert fakes["xp"].streak.call_args.args[0] == STUDENT
    assert fakes["quizzes"].list_assigned.call_args.args[0] == STUDENT
    assert fakes["uploads"].get_active_run.call_args.kwargs == {"user_id": str(STUDENT)}
    assert fakes["classes"].enrolled_class_ids.call_args.args[0] == STUDENT


def test_home_for_a_new_student_never_builds_the_boundary_store(
    tmp_path: Path, fakes: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise AssertionError("built the boundary store with nothing to grade")

    monkeypatch.setattr("lemely.web.routers.student_home.GradeBoundaryStore", refuse)
    response = _client(HistoryStore(tmp_path / "empty"), fakes).get("/api/student/home")
    assert response.status_code == 200, response.text
    assert response.json()["floor"] == []


def test_home_marking_moment_from_the_active_run(
    tmp_path: Path, fakes: dict[str, MagicMock]
) -> None:
    fakes["uploads"].get_active_run.return_value = MagicMock(
        id=uuid.uuid4(), status=UploadStatus.processing, original_filename="p.pdf", started_at=NOW
    )
    body = _client(HistoryStore(tmp_path / "h"), fakes).get("/api/student/home").json()
    assert body["moments"][0]["kind"] == "marking"


def test_home_with_a_malformed_id_returns_neutral_200(
    tmp_path: Path, fakes: dict[str, MagicMock]
) -> None:
    response = _client(HistoryStore(tmp_path / "h"), fakes, user_id="maya").get("/api/student/home")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["moments"] == []
    assert body["classCount"] == 0
    fakes["xp"].streak.assert_not_called()
