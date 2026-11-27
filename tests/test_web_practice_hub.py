"""Route tests for the Practice tab endpoints (L4).

The service is replaced with a stub, so these tests pin the HTTP contract:
shapes, status codes and the role gate. Service behaviour is covered by
``tests/test_practice_hub_repo.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.db.models.enums import Role
from lemely.db.practice_hub_repo import PastPaperRow, PastPaperUnavailableError, PracticeRun
from lemely.db.practice_repo import PracticeCreated, PracticeNotFoundError
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.routers.practice_hub import get_practice_hub_service

if TYPE_CHECKING:
    from collections.abc import Iterator

STUDENT = uuid.uuid4()
RUN = PracticeRun(
    assignment_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    subject_code="0625",
    title="Physics Practice Set",
    topics=["1 Motion"],
    status="in_progress",
    question_count=8,
    answered_count=3,
    awarded_marks=None,
    maximum_marks=None,
    time_limit_minutes=None,
    last_activity_at=datetime(2026, 11, 14, 9, 30, tzinfo=UTC),
)
PAPER = PastPaperRow(
    paper_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
    subject_code="0625",
    code="0625/41",
    paper_number=4,
    paper_variant=1,
    session_label="May/June 2023",
    duration_minutes=75,
    total_marks=80,
    question_count=18,
    awarded_marks=52,
    maximum_marks=80,
)
CREATED = PracticeCreated(
    assignment_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
    quiz_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
    question_count=18,
    requested_count=18,
    topics=["1 Motion"],
    reason=None,
)


class StubService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.create_error: Exception | None = None

    def runs(self, student_id: str, *, limit: int = 10) -> list[PracticeRun]:
        self.calls.append(("runs", (student_id, limit)))
        return [RUN]

    def past_papers(self, student_id: str, subject_code: str) -> list[PastPaperRow]:
        self.calls.append(("papers", (student_id, subject_code)))
        return [PAPER]

    def create_from_paper(self, student_id: str, paper_id: str, *, timed: bool) -> PracticeCreated:
        self.calls.append(("create", (student_id, paper_id, timed)))
        if self.create_error is not None:
            raise self.create_error
        uuid.UUID(paper_id)  # mirrors the real service's id validation
        return CREATED


@pytest.fixture
def stub() -> StubService:
    return StubService()


@pytest.fixture
def client(stub: StubService) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_practice_hub_service] = lambda: stub
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(client: TestClient, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(STUDENT), role=role.value
    )


def test_runs_shape_and_default_limit(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    res = client.get("/api/student/practice/runs")
    assert res.status_code == 200
    assert res.json() == {
        "runs": [
            {
                "assignmentId": "11111111-1111-1111-1111-111111111111",
                "subjectCode": "0625",
                "title": "Physics Practice Set",
                "topics": ["1 Motion"],
                "status": "in_progress",
                "questionCount": 8,
                "answeredCount": 3,
                "awardedMarks": None,
                "maximumMarks": None,
                "timeLimitMinutes": None,
                "lastActivityAt": "2026-11-14T09:30:00+00:00",
            }
        ]
    }
    assert stub.calls == [("runs", (str(STUDENT), 10))]


@pytest.mark.parametrize("limit", [0, 51])
def test_runs_limit_out_of_range_is_422(client: TestClient, limit: int) -> None:
    _as(client, Role.student)
    assert client.get(f"/api/student/practice/runs?limit={limit}").status_code == 422


def test_papers_shape(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    res = client.get("/api/student/practice/papers/0625")
    assert res.status_code == 200
    assert res.json() == {
        "subjectCode": "0625",
        "papers": [
            {
                "paperId": "22222222-2222-2222-2222-222222222222",
                "code": "0625/41",
                "subjectCode": "0625",
                "paperNumber": 4,
                "paperVariant": 1,
                "sessionLabel": "May/June 2023",
                "durationMinutes": 75,
                "totalMarks": 80,
                "questionCount": 18,
                "awardedMarks": 52,
                "maximumMarks": 80,
            }
        ],
    }
    assert stub.calls == [("papers", (str(STUDENT), "0625"))]


def test_create_from_paper_201(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    res = client.post(
        "/api/student/practice/papers/22222222-2222-2222-2222-222222222222", json={"timed": True}
    )
    assert res.status_code == 201
    assert res.json()["assignmentId"] == "33333333-3333-3333-3333-333333333333"
    assert res.json()["questionCount"] == 18
    assert stub.calls == [("create", (str(STUDENT), "22222222-2222-2222-2222-222222222222", True))]


def test_create_from_paper_defaults_to_untimed(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    res = client.post("/api/student/practice/papers/22222222-2222-2222-2222-222222222222", json={})
    assert res.status_code == 201
    assert stub.calls[0][1][2] is False


def test_create_from_unknown_paper_404(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    stub.create_error = PracticeNotFoundError("Unknown paper")
    assert client.post(f"/api/student/practice/papers/{uuid.uuid4()}", json={}).status_code == 404


def test_create_from_unservable_paper_409(client: TestClient, stub: StubService) -> None:
    _as(client, Role.student)
    stub.create_error = PastPaperUnavailableError("nothing servable")
    assert client.post(f"/api/student/practice/papers/{uuid.uuid4()}", json={}).status_code == 409


def test_create_from_paper_bad_id_422(client: TestClient) -> None:
    _as(client, Role.student)
    assert client.post("/api/student/practice/papers/not-a-uuid", json={}).status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/student/practice/runs"),
        ("get", "/api/student/practice/papers/0625"),
        ("post", "/api/student/practice/papers/22222222-2222-2222-2222-222222222222"),
    ],
)
def test_teacher_is_forbidden(client: TestClient, method: str, path: str) -> None:
    _as(client, Role.teacher)
    res = client.request(method, path, json={} if method == "post" else None)
    assert res.status_code == 403


def test_unauthenticated_is_401(client: TestClient) -> None:
    assert client.get("/api/student/practice/runs").status_code == 401


def test_existing_practice_routes_still_resolve(client: TestClient) -> None:
    """The new router must not shadow the generator's preview route."""
    _as(client, Role.teacher)
    # 403 (role gate on the generator router) proves the path still routes there, not 404/405.
    assert client.get("/api/student/practice/0625/preview").status_code == 403
