"""Authorization matrix for the FastAPI routes (P1.6).

Proves the RBAC guarantee for Phase 1: no route serves an unauthenticated caller
(missing/invalid token → 401) and no route serves the wrong role (→ 403). Student
routes require the ``student`` role; every teacher-portal route is staff-only
(teacher / school_admin / platform_admin) via the router-level guard.

**P4.10 chunk D (D4.22).** The two former IDOR endpoints (POST /student/plan,
POST /student/onboarding) were deleted along with their two explicit pins here.
Their replacements are covered instead, and the coverage is not symmetric
because the two routers are not guarded the same way:

* ``/api/student/study-plan/*`` carries a **router-level**
  ``require_role(Role.student)``, so this file's representative-spread
  convention (see the TEACHER_GET_ROUTES comment below) applies — one GET and
  one POST prove the guard for the router.
* ``/api/me/student-profile*`` does **not**. ``routers/me.py`` mounts a bare
  ``APIRouter(prefix="/api/me")`` and two of its routes
  (``/notification-preferences``, ``/profile``) are deliberately role-agnostic,
  so a spread would prove nothing about the routes it skipped. **Every one of
  the five student-only routes is listed individually**; drop one and its guard
  is unproven.
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

# (method, path) pairs. GET routes carry no body; every write route carries a
# minimal valid body so an auth failure (401/403) is never masked by a 422.
STUDENT_GET_ROUTES = [
    "/api/student/overview",
    "/api/student/subject/0625",
    "/api/student/result/0",
    "/api/student/standings",
    # Study plan (P4.7 chunk C) — router-level guard, representative spread.
    "/api/student/study-plan/0625",
    # Onboarding profile (P4.3) — per-route guards, so every route is listed.
    "/api/me/student-profile",
]
STUDENT_POST_ROUTES = [
    # /student/correct takes no body (the SSE self-mark stream); an empty POST
    # still hits the per-route student guard, so a wrong/absent role is 401/403.
    ("/api/student/correct", None),
    ("/api/student/study-plan", {"subjectCode": "0625"}),
    ("/api/me/student-profile/complete-onboarding", None),
]
# PATCH/PUT halves of the /api/me/student-profile surface. Listed separately
# because this file parametrizes by method, and individually because me.py has
# no router-level guard to generalise from.
STUDENT_PATCH_ROUTES = [("/api/me/student-profile", {"gradeLevel": "Year 11"})]
STUDENT_PUT_ROUTES = [
    ("/api/me/student-profile/enrolments", {"enrolments": []}),
    ("/api/me/student-profile/enrolments/0625/confidence-ratings", {"ratings": {}}),
]
# Teacher routes are gated at the router level, so proving the guard on a
# representative spread of GETs proves it for the whole router.
TEACHER_GET_ROUTES = [
    "/api/papers",
    "/api/papers/0",
    "/api/grading/queue",
    "/api/schemes",
    "/api/teacher/classes",
    "/api/classes/0",
    "/api/teacher/overview",
    "/api/quizzes/topics",
    "/api/quizzes/pools",
]
# School-admin seat surface. Gated at the router level to school_admin alone; a
# representative spread proves the guard for the whole router.
SCHOOL_GET_ROUTES = ["/api/school/seats"]
SCHOOL_POST_ROUTES = [
    ("/api/school/seats/invite", {"schoolId": "s1", "email": "new@student.local"}),
    (
        "/api/school/seats/00000000-0000-0000-0000-000000000000/revoke",
        None,
    ),
]

# Class model surface (D3.1/P3.1). Roster/enroll/remove-student are gated to the
# same staff triple as the rest of the teacher router (ownership is then
# enforced inside ClassService, not tested here — see test_class_repo.py);
# create/update/delete are further restricted per-route to teacher alone.
_CLASS_ID = "00000000-0000-0000-0000-000000000000"
_STUDENT_ID = "00000000-0000-0000-0000-000000000001"
CLASS_ROSTER_GET_ROUTES = [f"/api/classes/{_CLASS_ID}/roster"]
CLASS_CREATE_POST_ROUTES = [("/api/classes", {"name": "Physics 10A"})]
CLASS_UPDATE_PATCH_ROUTES = [(f"/api/classes/{_CLASS_ID}", {"name": "New name"})]
CLASS_DELETE_ROUTES = [f"/api/classes/{_CLASS_ID}"]
CLASS_ENROLL_POST_ROUTES = [(f"/api/classes/{_CLASS_ID}/enroll", {"studentId": _STUDENT_ID})]
CLASS_REMOVE_STUDENT_DELETE_ROUTES = [f"/api/classes/{_CLASS_ID}/students/{_STUDENT_ID}"]
# Self-enrolment lives on the student router, keyed off auth.user_id (D1.6).
STUDENT_JOIN_POST_ROUTES = [("/api/student/classes/join", {"joinCode": "ABC1234"})]


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
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object] | None
) -> None:
    app, _ = app_and_store
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 401, path


@pytest.mark.parametrize(("path", "body"), STUDENT_PATCH_ROUTES)
def test_student_patch_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object] | None
) -> None:
    app, _ = app_and_store
    resp = _client(app).patch(path, json=body)
    assert resp.status_code == 401, path


@pytest.mark.parametrize(("path", "body"), STUDENT_PUT_ROUTES)
def test_student_put_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object] | None
) -> None:
    app, _ = app_and_store
    resp = _client(app).put(path, json=body)
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


@pytest.mark.parametrize(("path", "body"), STUDENT_POST_ROUTES)
def test_student_post_rejects_non_student(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object] | None
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="t1", role=Role.teacher.value
    )
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 403, path


@pytest.mark.parametrize(("path", "body"), STUDENT_PATCH_ROUTES)
def test_student_patch_rejects_non_student(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object] | None
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="t1", role=Role.teacher.value
    )
    resp = _client(app).patch(path, json=body)
    assert resp.status_code == 403, path


@pytest.mark.parametrize(("path", "body"), STUDENT_PUT_ROUTES)
def test_student_put_rejects_non_student(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object] | None
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="t1", role=Role.teacher.value
    )
    resp = _client(app).put(path, json=body)
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
        # A real UUID, not the bare "staff" placeholder every other role check
        # in this file uses: ``GET /papers`` now parses ``auth.user_id`` as a
        # UUID for DS11 visibility (Task 6 — papers moved onto
        # ``TeacherPaperRepository``), where a real token's ``sub`` always is
        # one. This caller owns no papers, so the route still answers 200
        # with an empty list; the point here is only the role gate.
        app.dependency_overrides[get_auth_context] = lambda role=role: AuthContext(  # type: ignore[attr-defined]
            user_id="00000000-0000-0000-0000-0000000000aa", role=role.value
        )
        resp = _client(app).get("/api/papers")
        assert resp.status_code == 200, role


# ── School-admin seat surface: staff-gated to school_admin alone ──────────────


@pytest.mark.parametrize("path", SCHOOL_GET_ROUTES)
def test_school_get_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str
) -> None:
    app, _ = app_and_store
    resp = _client(app).get(path)
    assert resp.status_code == 401, path
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.parametrize(("path", "body"), SCHOOL_POST_ROUTES)
def test_school_post_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object] | None
) -> None:
    app, _ = app_and_store
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 401, path


@pytest.mark.parametrize("role", [Role.student, Role.parent, Role.teacher, Role.platform_admin])
def test_school_get_rejects_non_school_admin(
    app_and_store: tuple[object, HistoryStore], role: Role
) -> None:
    """Even platform_admin is 403 here — no super-role at the route layer (D1.6)."""
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda role=role: AuthContext(  # type: ignore[attr-defined]
        user_id="u1", role=role.value
    )
    resp = _client(app).get("/api/school/seats")
    assert resp.status_code == 403, role


@pytest.mark.parametrize(("path", "body"), SCHOOL_POST_ROUTES)
def test_school_post_rejects_student(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object] | None
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="s1", role=Role.student.value
    )
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 403, path


# ── Class model surface (D3.1/P3.1) ────────────────────────────────────────────
#
# Ownership itself (a teacher only reaching their own classes, school_admin
# only their own schools) is proven against real Postgres in
# test_class_repo.py; here only the router-level role gate is exercised, so
# these tests never touch the database (a rejection is raised by
# ``require_role`` before ``get_class_service`` is ever resolved).


@pytest.mark.parametrize("path", CLASS_ROSTER_GET_ROUTES)
def test_class_roster_get_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str
) -> None:
    app, _ = app_and_store
    resp = _client(app).get(path)
    assert resp.status_code == 401, path


@pytest.mark.parametrize(("path", "body"), CLASS_CREATE_POST_ROUTES)
def test_class_create_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object]
) -> None:
    app, _ = app_and_store
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 401, path


@pytest.mark.parametrize(("path", "body"), CLASS_UPDATE_PATCH_ROUTES)
def test_class_update_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object]
) -> None:
    app, _ = app_and_store
    resp = _client(app).patch(path, json=body)
    assert resp.status_code == 401, path


@pytest.mark.parametrize("path", CLASS_DELETE_ROUTES)
def test_class_delete_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str
) -> None:
    app, _ = app_and_store
    resp = _client(app).delete(path)
    assert resp.status_code == 401, path


@pytest.mark.parametrize(("path", "body"), CLASS_ENROLL_POST_ROUTES)
def test_class_enroll_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object]
) -> None:
    app, _ = app_and_store
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 401, path


@pytest.mark.parametrize("path", CLASS_REMOVE_STUDENT_DELETE_ROUTES)
def test_class_remove_student_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str
) -> None:
    app, _ = app_and_store
    resp = _client(app).delete(path)
    assert resp.status_code == 401, path


@pytest.mark.parametrize(("path", "body"), STUDENT_JOIN_POST_ROUTES)
def test_student_join_without_token_is_401(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object]
) -> None:
    app, _ = app_and_store
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 401, path


@pytest.mark.parametrize("path", CLASS_ROSTER_GET_ROUTES)
def test_class_roster_get_rejects_student(
    app_and_store: tuple[object, HistoryStore], path: str
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="s1", role=Role.student.value
    )
    resp = _client(app).get(path)
    assert resp.status_code == 403, path


@pytest.mark.parametrize("path", CLASS_ROSTER_GET_ROUTES)
def test_class_roster_get_rejects_parent(
    app_and_store: tuple[object, HistoryStore], path: str
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="p1", role=Role.parent.value
    )
    resp = _client(app).get(path)
    assert resp.status_code == 403, path


@pytest.mark.parametrize(("path", "body"), CLASS_CREATE_POST_ROUTES)
def test_class_create_rejects_student(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object]
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="s1", role=Role.student.value
    )
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 403, path


@pytest.mark.parametrize("role", [Role.school_admin, Role.platform_admin])
@pytest.mark.parametrize(("path", "body"), CLASS_CREATE_POST_ROUTES)
def test_class_create_rejects_non_teacher_staff(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object], role: Role
) -> None:
    """Create is owner-scoped to teacher alone: even school_admin is 403 here."""
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda role=role: AuthContext(  # type: ignore[attr-defined]
        user_id="u1", role=role.value
    )
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 403, (path, role)


@pytest.mark.parametrize("role", [Role.school_admin, Role.platform_admin, Role.student])
@pytest.mark.parametrize(("path", "body"), CLASS_UPDATE_PATCH_ROUTES)
def test_class_update_rejects_non_teacher(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object], role: Role
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda role=role: AuthContext(  # type: ignore[attr-defined]
        user_id="u1", role=role.value
    )
    resp = _client(app).patch(path, json=body)
    assert resp.status_code == 403, (path, role)


@pytest.mark.parametrize("role", [Role.school_admin, Role.platform_admin, Role.student])
@pytest.mark.parametrize("path", CLASS_DELETE_ROUTES)
def test_class_delete_rejects_non_teacher(
    app_and_store: tuple[object, HistoryStore], path: str, role: Role
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda role=role: AuthContext(  # type: ignore[attr-defined]
        user_id="u1", role=role.value
    )
    resp = _client(app).delete(path)
    assert resp.status_code == 403, (path, role)


@pytest.mark.parametrize(("path", "body"), CLASS_ENROLL_POST_ROUTES)
def test_class_enroll_rejects_student(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object]
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="s1", role=Role.student.value
    )
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 403, path


@pytest.mark.parametrize("path", CLASS_REMOVE_STUDENT_DELETE_ROUTES)
def test_class_remove_student_rejects_student(
    app_and_store: tuple[object, HistoryStore], path: str
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id="s1", role=Role.student.value
    )
    resp = _client(app).delete(path)
    assert resp.status_code == 403, path


@pytest.mark.parametrize(
    "role", [Role.teacher, Role.school_admin, Role.platform_admin, Role.parent]
)
@pytest.mark.parametrize(("path", "body"), STUDENT_JOIN_POST_ROUTES)
def test_student_join_rejects_non_student(
    app_and_store: tuple[object, HistoryStore], path: str, body: dict[str, object], role: Role
) -> None:
    app, _ = app_and_store
    app.dependency_overrides[get_auth_context] = lambda role=role: AuthContext(  # type: ignore[attr-defined]
        user_id="u1", role=role.value
    )
    resp = _client(app).post(path, json=body)
    assert resp.status_code == 403, (path, role)


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
