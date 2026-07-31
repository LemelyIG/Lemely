"""Authorization matrix for the FastAPI routes (P1.6).

Proves the RBAC guarantee for Phase 1: no route serves an unauthenticated caller
(missing/invalid token → 401) and no route serves the wrong role (→ 403). Student
routes require the ``student`` role; every teacher-portal route is staff-only
(teacher / school_admin / platform_admin) via the router-level guard.

The two former IDOR endpoints (POST /student/plan, POST /student/onboarding) get
explicit coverage: they no longer accept a caller-supplied id and now require a
student token, so identity is the authenticated caller alone.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.auth.tokens import mint_access_token
from lemely.db.models.enums import Role
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import Settings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_history_store, get_settings

if TYPE_CHECKING:
    from pathlib import Path

# (method, path) pairs. GET routes carry no body; the two student POSTs carry a
# minimal valid body so an auth failure (401/403) is never masked by a 422.
STUDENT_GET_ROUTES = [
    "/api/student/overview",
    "/api/student/subject/0625",
    "/api/student/result/0",
    "/api/student/plan",
    "/api/student/standings",
]
STUDENT_POST_ROUTES = [
    ("/api/student/plan", {"weeklyHours": 6.0}),
    ("/api/student/onboarding", {"weeklyHours": 5.0, "sliders": []}),
]
# Teacher routes are gated at the router level, so proving the guard on a
# representative spread of GETs proves it for the whole router.
TEACHER_GET_ROUTES = [
    "/api/papers",
    "/api/grading/queue",
    "/api/schemes",
    "/api/teacher/classes",
    "/api/teacher/overview",
    "/api/quizzes/topics",
    "/api/quizzes/pools",
]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    base = Settings()
    data = base.model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    return Settings.model_validate(data)


@pytest.fixture
def app_and_store(settings: Settings) -> tuple[object, HistoryStore]:
    store = HistoryStore(settings.paths.output_dir / "history")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_history_store] = lambda: store
    return app, store


def _client(app: object) -> TestClient:
    return TestClient(app)  # type: ignore[arg-type]


# ── No token → 401 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", STUDENT_GET_ROUTES + TEACHER_GET_ROUTES)
def test_get_without_token_is_401(app_and_store: tuple[object, HistoryStore], path: str) -> None:
    app, _ = app_and_store
    resp = _client(app).get(path)
    assert resp.status_code == 401, path
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.parametrize(("path", "body"), STUDENT_POST_ROUTES)
def test_post_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object]
) -> None:
    app, _ = app_and_store
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 401, path


# ── Wrong role → 403 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", STUDENT_GET_ROUTES)
def test_student_route_rejects_non_student(
    app_and_store: tuple[object, HistoryStore], path: str
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="t1", role=Role.teacher.value
    )
    resp = _client(app).get(path)
    assert resp.status_code == 403, path


@pytest.mark.parametrize("path", TEACHER_GET_ROUTES)
def test_teacher_route_rejects_student(
    app_and_store: tuple[object, HistoryStore], path: str
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="s1", role=Role.student.value
    )
    resp = _client(app).get(path)
    assert resp.status_code == 403, path


def test_teacher_route_accepts_school_admin_and_platform_admin(
    app_and_store: tuple[object, HistoryStore],
) -> None:
    app, _ = app_and_store
    for role in (Role.school_admin, Role.platform_admin, Role.teacher):
        app.dependency_overrides[get_auth_context] = lambda role=role: AuthContext(  # type: ignore[attr-defined]
            user_id="staff", role=role.value
        )
        resp = _client(app).get("/api/papers")
        assert resp.status_code == 200, role


# ── IDOR kill: identity is the token, never the payload ───────────────────────


def test_plan_post_ignores_any_caller_supplied_id(
    app_and_store: tuple[object, HistoryStore],
) -> None:
    """A student token drives the plan; a stray studentId in the body is rejected."""
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="victim-id", role=Role.student.value
    )
    client = _client(app)
    ok = client.post("/api/student/plan", json={"weeklyHours": 6.0})
    assert ok.status_code == 200
    assert ok.json()["studentId"] == "victim-id"
    # extra="forbid": smuggling another student's id is a 422, not honoured.
    smuggle = client.post(
        "/api/student/plan", json={"studentId": "someone-else", "weeklyHours": 6.0}
    )
    assert smuggle.status_code == 422


def test_onboarding_uses_token_identity(app_and_store: tuple[object, HistoryStore]) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="real-student", role=Role.student.value
    )
    resp = _client(app).post("/api/student/onboarding", json={"weeklyHours": 5.0, "sliders": []})
    assert resp.status_code == 200
    assert resp.json()["studentId"] == "real-student"


# ── End-to-end with a real minted token (no override) ─────────────────────────


def test_real_student_token_reaches_student_route(
    app_and_store: tuple[object, HistoryStore], settings: Settings
) -> None:
    app, _ = app_and_store
    token = mint_access_token(
        user_id=uuid.uuid4(), settings=settings, app_role=Role.student.value, provider="email"
    )
    resp = _client(app).get("/api/student/overview", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_real_student_token_blocked_from_teacher_route(
    app_and_store: tuple[object, HistoryStore], settings: Settings
) -> None:
    app, _ = app_and_store
    token = mint_access_token(
        user_id=uuid.uuid4(), settings=settings, app_role=Role.student.value, provider="email"
    )
    resp = _client(app).get("/api/papers", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
