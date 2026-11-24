"""``GET /api/student/subject/{code}``: the redesign L2 additions.

The boundary store is replaced with a fixed fake so each assertion names the
exact boundary it was computed from; ``tests/test_web_student.py`` keeps the
real-store coverage of the fields that existed before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.io.history_store import HistoryStore
from lemely.runtime.errors import EmptyGradeBoundaryStoreError
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_history_store,
    get_student_profile_service,
)

if TYPE_CHECKING:
    from pathlib import Path

    from lemely.io.grade_boundaries import BoundarySource

STUDENT_ID = "maya"


class _FakeBoundaryStore:
    """Paper 4 resolves exactly, Paper 2 to the subject default."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def resolve(self, metadata: ExamMetadata) -> tuple[dict[str, float], BoundarySource]:
        if metadata.paper_number == 4:
            return {"A*": 85.0, "A": 72.0, "B": 60.0, "C": 48.0}, "exact"
        return {"A*": 85.71, "A": 72.0, "B": 60.0}, "subject_default"


def _weak(topic: str, lost: int, maximum: int) -> WeakArea:
    return WeakArea(
        topic=topic,
        lost_marks=lost,
        maximum_marks=maximum,
        accuracy=round(1.0 - lost / maximum, 4),
        question_ids=["q1"],
    )


def _rec(
    *,
    paper: int,
    variant: int,
    awarded: int,
    maximum: int,
    grade: str,
    recorded_at: str,
    weak: list[WeakArea] | None = None,
    origin: str = "past_paper",
) -> PaperRecord:
    return PaperRecord(
        student_id=STUDENT_ID,
        metadata=ExamMetadata(
            subject_code="0580",
            paper_number=paper,
            paper_variant=variant,
            session_month="May/June",
            session_year=2024,
        ),
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=round(awarded / maximum * 100.0, 2),
        grade=grade,
        weak_areas=weak or [],
        recorded_at=recorded_at,
        origin=origin,  # type: ignore[arg-type]
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("lemely.web.routers.student.GradeBoundaryStore", _FakeBoundaryStore)
    store = HistoryStore(tmp_path / "history")
    # Full-history indices: 0 P4, 1 P2, 2 quiz, 3 P4, 4 P2.
    store.append(
        STUDENT_ID,
        _rec(
            paper=4,
            variant=1,
            awarded=45,
            maximum=80,
            grade="C",
            recorded_at="2023-10-15T10:00:00+00:00",
            weak=[_weak("C7 Vectors", 10, 14), _weak("C2 Algebra", 6, 12)],
        ),
    )
    store.append(
        STUDENT_ID,
        _rec(
            paper=2,
            variant=2,
            awarded=44,
            maximum=70,
            grade="B",
            recorded_at="2023-11-15T10:00:00+00:00",
            weak=[_weak("C2 Algebra", 8, 12)],
        ),
    )
    store.append(
        STUDENT_ID,
        _rec(
            paper=1,
            variant=1,
            awarded=3,
            maximum=10,
            grade="",
            recorded_at="2023-12-15T10:00:00+00:00",
            origin="quiz",
            weak=[_weak("C9 Probability", 7, 10)],
        ),
    )
    store.append(
        STUDENT_ID,
        _rec(
            paper=4,
            variant=2,
            awarded=61,
            maximum=80,
            grade="A",
            recorded_at="2024-04-15T10:00:00+00:00",
            weak=[_weak("C7 Vectors", 8, 14)],
        ),
    )
    store.append(
        STUDENT_ID,
        _rec(
            paper=2,
            variant=1,
            awarded=53,
            maximum=70,
            grade="A",
            recorded_at="2024-03-15T10:00:00+00:00",
        ),
    )
    profile_service = MagicMock()
    profile_service.list_enrolments.return_value = []
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_student_profile_service] = lambda: profile_service
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    return TestClient(app)


def _paper(body: dict, number: int) -> dict:
    return next(p for p in body["papersBreakdown"] if p["paperNumber"] == number)


def test_each_paper_carries_its_attempts_in_marks_oldest_first(client: TestClient) -> None:
    body = client.get("/api/student/subject/0580").json()

    p4 = _paper(body, 4)
    assert p4["outOf"] == 80
    assert [(a["id"], a["awarded"], a["maximum"], a["grade"]) for a in p4["attempts"]] == [
        ("0", 45, 80, "C"),
        ("3", 61, 80, "A"),
    ]
    assert p4["attempts"][-1]["label"] == "0580/42 · May/Jun 2024"
    assert p4["attempts"][0]["recordedAt"] == "2023-10-15T10:00:00+00:00"


def test_quizzes_never_become_attempts_or_papers(client: TestClient) -> None:
    body = client.get("/api/student/subject/0580").json()

    assert sorted(p["paperNumber"] for p in body["papersBreakdown"]) == [2, 4]
    ids = [a["id"] for p in body["papersBreakdown"] for a in p["attempts"]]
    assert "2" not in ids
    assert [row["id"] for row in body["paperHistory"]] == ["4", "3", "1", "0"]


def test_each_paper_has_its_own_goal_line_from_the_boundary_table(client: TestClient) -> None:
    body = client.get("/api/student/subject/0580").json()

    p4_goal = _paper(body, 4)["goal"]
    assert p4_goal == {
        "grade": "A*",
        "marks": 68,
        "outOf": 80,
        "source": "exact",
        "sourceLabel": "May/Jun 2024 boundary",
    }
    p2_goal = _paper(body, 2)["goal"]
    assert p2_goal["marks"] == 60  # 85.71% of 70 = 59.997
    assert p2_goal["sourceLabel"] == "Average of past boundaries"
    assert _paper(body, 4)["boundary"] == "A* line 68/80"


def test_history_rows_carry_structured_marks_and_labels(client: TestClient) -> None:
    row = client.get("/api/student/subject/0580").json()["paperHistory"][0]

    assert row["id"] == "4"
    assert row["awarded"] == 53
    assert row["maximum"] == 70
    assert row["paperNumber"] == 2
    assert row["recordedAt"] == "2024-03-15T10:00:00+00:00"
    assert row["label"] == "0580/21 · May/Jun 2024"
    assert row["marks"] == "53/70"  # the pre-existing field keeps its meaning


def test_topics_carry_numeric_accuracy_and_marks_to_win(client: TestClient) -> None:
    topics = {t["name"]: t for t in client.get("/api/student/subject/0580").json()["topicMap"]}

    # Vectors: lost 10/14 then 8/14 -> accuracy 1 - 18/28 = 36%; mean lost 9.
    assert topics["C7 Vectors"]["accuracy"] == 36
    assert topics["C7 Vectors"]["marksToWin"] == 9
    # Algebra: 6/12 on P4, 8/12 on P2 -> mean 7.
    assert topics["C2 Algebra"]["marksToWin"] == 7
    # Probability appears only in the quiz: on the map (K16), but no paper marks to win.
    assert topics["C9 Probability"]["accuracy"] == 30
    assert topics["C9 Probability"]["marksToWin"] == 0


def test_only_quizzes_is_still_a_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lemely.web.routers.student.GradeBoundaryStore", _FakeBoundaryStore)
    store = HistoryStore(tmp_path / "history")
    store.append(
        STUDENT_ID,
        _rec(
            paper=1,
            variant=1,
            awarded=3,
            maximum=10,
            grade="",
            recorded_at="2024-01-15T10:00:00+00:00",
            origin="quiz",
        ),
    )
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )

    assert TestClient(app).get("/api/student/subject/0580").status_code == 404


def test_forecast_is_the_weighted_mean_of_papers_only(client: TestClient) -> None:
    """K7/K16: 203/300 over the four graded papers is 68%; the 3/10 quiz would make it 66%.

    With the fixture's boundaries 68% reads as a B. The latest paper alone
    (53/70, 75.7%) would read as an A, so this also pins the forecast to the
    weighted mean rather than the latest result.
    """
    header = client.get("/api/student/subject/0580").json()["header"]

    assert header["weightedMean"] == "68"
    assert header["forecast"] == "B"


def test_forecast_resolves_against_the_latest_papers_boundaries(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """K7: the same 68% is an A on Paper 2's table and a B on Paper 4's.

    The latest graded record is Paper 2, so its table decides. Reading the
    first record's (Paper 4's) table instead would turn this A into a B.
    """

    class _TablePerPaper(_FakeBoundaryStore):
        def resolve(self, metadata: ExamMetadata) -> tuple[dict[str, float], BoundarySource]:
            if metadata.paper_number == 4:
                return {"A": 70.0, "B": 50.0}, "exact"
            return {"A": 60.0, "B": 40.0}, "exact"

    monkeypatch.setattr("lemely.web.routers.student.GradeBoundaryStore", _TablePerPaper)

    assert client.get("/api/student/subject/0580").json()["header"]["forecast"] == "A"


def test_an_un_ingested_boundary_store_is_a_503_never_invented_boundaries(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """K21: a student with papers cannot be forecast until thresholds are ingested.

    The subject route builds the store itself, so the app's one handler for
    ``EmptyGradeBoundaryStoreError`` must reach it: 503 naming the ingest, not
    a 200 whose goal lines and forecast came from made-up boundaries.
    """

    def _empty(*_args: object, **_kwargs: object) -> None:
        raise EmptyGradeBoundaryStoreError("component_thresholds has no verified rows")

    monkeypatch.setattr("lemely.web.routers.student.GradeBoundaryStore", _empty)
    response = client.get("/api/student/subject/0580")

    assert response.status_code == 503, response.text
    assert "ingest_thresholds" in response.json()["detail"]
