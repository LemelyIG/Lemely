"""Exhaustive, generated authorization matrix over **every** route (P6.3).

``tests/test_authz_matrix.py`` (P1.6) proves the RBAC guarantee on a *hand-listed*
spread of routes. That list stopped growing at Phase 3: the Phase-4 and Phase-5
routers (flashcards, friends, leaderboard, xp, notifications, practice, placement,
announcements, exam calendar, parent portal) are almost entirely absent from it,
and nothing made adding a route fail a test. This file closes that hole, and is
the file MISSION §4's Phase-6 "authz matrix re-verified" criterion is measured on.

Three properties, in increasing strength:

1. :func:`test_every_route_is_declared` — the app's route set and ``EXPECTED``'s
   key set are **equal**. A new route with no entry fails; a deleted route with a
   stale entry fails. This is the drift gate the hand-listed matrix never had.
2. :func:`test_declared_guard_matches_the_wired_guard` — the guard declared here
   equals the guard actually wired into the route's dependency tree, read out of
   the ``require_role`` closure. Catches a route that keeps its entry but quietly
   loses or widens its guard.
3. The behavioural pair — every non-public route answers **401** to an
   unauthenticated caller, and every role-gated route answers **403** to each of
   the five platform roles it does not name. These issue real requests and are
   the actual proof; 1 and 2 only guarantee they are asked about every route.

**On the provenance of EXPECTED, stated plainly:** its rows were seeded from the
wired guards and then reviewed against MISSION §1/§3's role model, not derived
independently. So property 2 is a *freeze* of a reviewed state, not an
independent check of it — its value is that any later change must be made twice,
deliberately. Properties 1 and 3 are independent of how the table was produced.

The 403 sweep never reaches a handler: ``require_role`` raises before any service
or session dependency resolves, so this file needs no database.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from lemely.auth.tokens import mint_access_token
from lemely.db.models.enums import Role
from lemely.runtime.config import Settings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi import FastAPI
    from fastapi.dependencies.models import Dependant

# Guard vocabulary. ``PUBLIC`` means no authentication at all; ``AUTH_ANY`` means
# authenticated but deliberately role-agnostic (the /api/me and notification
# surfaces every signed-in role shares).
PUBLIC = "PUBLIC"
AUTH_ANY = "AUTH_ANY"
STUDENT = frozenset({"student"})
PARENT = frozenset({"parent"})
TEACHER = frozenset({"teacher"})
SCHOOL_ADMIN = frozenset({"school_admin"})
TEACHER_OR_SCHOOL_ADMIN = frozenset({"teacher", "school_admin"})
STAFF = frozenset({"teacher", "school_admin", "platform_admin"})

ALL_ROLES = frozenset(role.value for role in Role)

# (method, path) → the guard that route must carry. Reviewed, not inferred.
EXPECTED: dict[tuple[str, str], str | frozenset[str]] = {
    # ── TEACHER (3) ────────────────────
    ("POST", "/api/classes"): TEACHER,
    ("DELETE", "/api/classes/{class_id}"): TEACHER,
    ("PATCH", "/api/classes/{class_id}"): TEACHER,
    # ── SCHOOL_ADMIN (3) ────────────────────
    ("GET", "/api/school/seats"): SCHOOL_ADMIN,
    ("POST", "/api/school/seats/invite"): SCHOOL_ADMIN,
    ("POST", "/api/school/seats/{seat_id}/revoke"): SCHOOL_ADMIN,
    # ── TEACHER_OR_SCHOOL_ADMIN (3) ────────────────────
    ("GET", "/api/teacher/announcements"): TEACHER_OR_SCHOOL_ADMIN,
    ("POST", "/api/teacher/announcements"): TEACHER_OR_SCHOOL_ADMIN,
    ("DELETE", "/api/teacher/announcements/{announcement_id}"): TEACHER_OR_SCHOOL_ADMIN,
    # ── PARENT (4) ────────────────────
    ("GET", "/api/parent/children"): PARENT,
    ("GET", "/api/parent/children/{child_id}"): PARENT,
    ("GET", "/api/parent/children/{child_id}/subjects/{code}"): PARENT,
    ("GET", "/api/parent/children/{child_id}/weaknesses"): PARENT,
    # ── PUBLIC (5) ────────────────────
    ("POST", "/api/auth/login"): PUBLIC,
    ("POST", "/api/auth/otp/request"): PUBLIC,
    ("POST", "/api/auth/otp/verify"): PUBLIC,
    ("POST", "/api/auth/signup"): PUBLIC,
    ("GET", "/api/health"): PUBLIC,
    # ── AUTH_ANY (12) ────────────────────
    ("GET", "/api/me/devices"): AUTH_ANY,
    ("DELETE", "/api/me/devices/{device_id}"): AUTH_ANY,
    ("GET", "/api/me/notification-preferences"): AUTH_ANY,
    ("PUT", "/api/me/notification-preferences"): AUTH_ANY,
    ("GET", "/api/me/profile"): AUTH_ANY,
    ("GET", "/api/notifications"): AUTH_ANY,
    ("GET", "/api/notifications/counts"): AUTH_ANY,
    ("GET", "/api/notifications/push/config"): AUTH_ANY,
    ("POST", "/api/notifications/push/subscribe"): AUTH_ANY,
    ("POST", "/api/notifications/push/unsubscribe"): AUTH_ANY,
    ("POST", "/api/notifications/read-all"): AUTH_ANY,
    ("POST", "/api/notifications/{notification_id}/read"): AUTH_ANY,
    # ── STAFF (40) ────────────────────
    ("GET", "/api/classes/{class_id}"): STAFF,
    ("GET", "/api/classes/{class_id}/analytics"): STAFF,
    ("POST", "/api/classes/{class_id}/enroll"): STAFF,
    ("GET", "/api/classes/{class_id}/roster"): STAFF,
    ("DELETE", "/api/classes/{class_id}/students/{student_id}"): STAFF,
    ("GET", "/api/grading/queue"): STAFF,
    ("GET", "/api/papers"): STAFF,
    ("POST", "/api/papers/upload"): STAFF,
    ("GET", "/api/papers/{paper_id}"): STAFF,
    ("POST", "/api/papers/{paper_id}/extract"): STAFF,
    ("POST", "/api/papers/{paper_id}/grade"): STAFF,
    ("POST", "/api/quizzes/generate"): STAFF,
    ("GET", "/api/quizzes/pools"): STAFF,
    ("POST", "/api/quizzes/preview"): STAFF,
    ("GET", "/api/quizzes/topics"): STAFF,
    ("GET", "/api/schemes"): STAFF,
    ("POST", "/api/schemes"): STAFF,
    ("GET", "/api/teacher/at-risk"): STAFF,
    ("POST", "/api/teacher/at-risk/{student_id}/acknowledge"): STAFF,
    ("DELETE", "/api/teacher/at-risk/{student_id}/acknowledge/{reason}"): STAFF,
    ("GET", "/api/teacher/classes"): STAFF,
    ("GET", "/api/teacher/overview"): STAFF,
    ("GET", "/api/teacher/quizzes"): STAFF,
    ("POST", "/api/teacher/quizzes"): STAFF,
    ("GET", "/api/teacher/quizzes/pool-count"): STAFF,
    ("GET", "/api/teacher/quizzes/{quiz_id}"): STAFF,
    ("PATCH", "/api/teacher/quizzes/{quiz_id}"): STAFF,
    ("GET", "/api/teacher/quizzes/{quiz_id}/assignments"): STAFF,
    ("POST", "/api/teacher/quizzes/{quiz_id}/assignments"): STAFF,
    ("DELETE", "/api/teacher/quizzes/{quiz_id}/assignments/{assignment_id}"): STAFF,
    ("GET", "/api/teacher/quizzes/{quiz_id}/assignments/{assignment_id}/results"): STAFF,
    ("POST", "/api/teacher/quizzes/{quiz_id}/questions/generate"): STAFF,
    ("DELETE", "/api/teacher/quizzes/{quiz_id}/questions/{question_ref}"): STAFF,
    ("POST", "/api/teacher/quizzes/{quiz_id}/status"): STAFF,
    ("GET", "/api/teacher/review"): STAFF,
    ("POST", "/api/teacher/review/bulk-approve"): STAFF,
    ("GET", "/api/teacher/review/{item_id}"): STAFF,
    ("POST", "/api/teacher/review/{item_id}/dismiss"): STAFF,
    ("POST", "/api/teacher/review/{item_id}/resolve"): STAFF,
    ("GET", "/api/teacher/students/{student_id}"): STAFF,
    # ── STUDENT (51) ────────────────────
    ("GET", "/api/me/student-profile"): STUDENT,
    ("PATCH", "/api/me/student-profile"): STUDENT,
    ("POST", "/api/me/student-profile/complete-onboarding"): STUDENT,
    ("PUT", "/api/me/student-profile/enrolments"): STUDENT,
    ("PUT", "/api/me/student-profile/enrolments/{subject_code}/confidence-ratings"): STUDENT,
    ("GET", "/api/student/announcements"): STUDENT,
    ("GET", "/api/student/announcements/unread-count"): STUDENT,
    ("POST", "/api/student/announcements/{announcement_id}/read"): STUDENT,
    ("GET", "/api/student/classes"): STUDENT,
    ("POST", "/api/student/classes/join"): STUDENT,
    ("POST", "/api/student/correct"): STUDENT,
    ("GET", "/api/student/exam-calendar"): STUDENT,
    ("DELETE", "/api/student/flashcards/cards/{card_id}"): STUDENT,
    ("PATCH", "/api/student/flashcards/cards/{card_id}"): STUDENT,
    ("POST", "/api/student/flashcards/cards/{card_id}/review"): STUDENT,
    ("GET", "/api/student/flashcards/decks"): STUDENT,
    ("POST", "/api/student/flashcards/decks"): STUDENT,
    ("POST", "/api/student/flashcards/decks/generate"): STUDENT,
    ("DELETE", "/api/student/flashcards/decks/{deck_id}"): STUDENT,
    ("GET", "/api/student/flashcards/decks/{deck_id}"): STUDENT,
    ("POST", "/api/student/flashcards/decks/{deck_id}/cards"): STUDENT,
    ("GET", "/api/student/flashcards/due"): STUDENT,
    ("GET", "/api/student/friends"): STUDENT,
    ("POST", "/api/student/friends/requests"): STUDENT,
    ("DELETE", "/api/student/friends/{friendship_id}"): STUDENT,
    ("POST", "/api/student/friends/{friendship_id}/accept"): STUDENT,
    ("GET", "/api/student/leaderboard"): STUDENT,
    ("GET", "/api/student/overview"): STUDENT,
    ("GET", "/api/student/parent-links"): STUDENT,
    ("POST", "/api/student/parent-links"): STUDENT,
    ("DELETE", "/api/student/parent-links/{parent_id}"): STUDENT,
    ("POST", "/api/student/placement"): STUDENT,
    ("GET", "/api/student/placement/{assignment_id}/result"): STUDENT,
    ("GET", "/api/student/placement/{subject_code}/availability"): STUDENT,
    ("POST", "/api/student/practice"): STUDENT,
    ("GET", "/api/student/practice/{assignment_id}/export"): STUDENT,
    ("GET", "/api/student/practice/{assignment_id}/result"): STUDENT,
    ("GET", "/api/student/practice/{subject_code}/preview"): STUDENT,
    ("GET", "/api/student/practice/{subject_code}/topics"): STUDENT,
    ("GET", "/api/student/quizzes"): STUDENT,
    ("GET", "/api/student/quizzes/{assignment_id}"): STUDENT,
    ("PUT", "/api/student/quizzes/{assignment_id}/answers/{question_ref}"): STUDENT,
    ("POST", "/api/student/quizzes/{assignment_id}/submit"): STUDENT,
    ("GET", "/api/student/result/{paper_id}"): STUDENT,
    ("GET", "/api/student/standings"): STUDENT,
    ("POST", "/api/student/study-plan"): STUDENT,
    ("POST", "/api/student/study-plan/sessions/{session_id}/complete"): STUDENT,
    ("GET", "/api/student/study-plan/{subject_code}"): STUDENT,
    ("GET", "/api/student/subject/{code}"): STUDENT,
    ("POST", "/api/student/uploads"): STUDENT,
    ("GET", "/api/student/xp"): STUDENT,
}


def _flatten(router: object) -> list[APIRoute]:
    """Collect every ``APIRoute`` in the app.

    FastAPI keeps an included router as an ``_IncludedRouter`` wrapper on
    ``app.routes`` rather than flattening its routes into the app, so a plain
    ``for r in app.routes`` sees only the four docs routes. Recurse through
    ``original_router`` instead. (``app.openapi()["paths"]`` would give the same
    path set but not the dependency tree property 2 needs.)
    """
    found: list[APIRoute] = []
    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            found.append(route)
        else:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                found.extend(_flatten(inner))
    return found


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk(sub)


def _wired_guard(route: APIRoute) -> str | frozenset[str]:
    """Read the guard actually wired into ``route`` out of its dependency tree.

    ``require_role`` returns a closure named ``_guard`` holding the allowed role
    values in a free variable; a route can carry more than one (router-level plus
    per-route), and both must pass, so the effective set is their intersection.
    """
    roles: set[str] | None = None
    authenticated = False
    for dependant in _walk(route.dependant):
        call = dependant.call
        if call is get_auth_context:
            authenticated = True
        if call is None or getattr(call, "__name__", "") != "_guard" or not call.__closure__:
            continue
        cells = dict(zip(call.__code__.co_freevars, call.__closure__, strict=True))
        allowed = cells["allowed_values"].cell_contents
        roles = set(allowed) if roles is None else roles & set(allowed)
    if roles is not None:
        return frozenset(roles)
    return AUTH_ANY if authenticated else PUBLIC


# Placeholder path-parameter values. Never reached — the guard rejects first —
# but they must route, so ``{...}`` cannot be left in the URL.
_PLACEHOLDERS = {
    "code": "0625",
    "subject_code": "0625",
    "question_ref": "1a",
    "reason": "declining_trend",
    "paper_id": "0",
}


def _concrete(path: str) -> str:
    out = path
    while "{" in out:
        name = out[out.index("{") + 1 : out.index("}")]
        out = out.replace(f"{{{name}}}", _PLACEHOLDERS.get(name, str(uuid.uuid4())), 1)
    return out


ROUTES = sorted(
    (method, route.path)
    for route in _flatten(create_app().router)
    for method in route.methods
    if method not in {"HEAD", "OPTIONS"}
)
_NON_PUBLIC = [(m, p) for m, p in ROUTES if EXPECTED.get((m, p)) != PUBLIC]
_ROLE_GATED = [
    (m, p, role)
    for m, p in ROUTES
    if isinstance(EXPECTED.get((m, p)), frozenset)
    for role in sorted(ALL_ROLES - EXPECTED[(m, p)])  # type: ignore[operator]
]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = Settings().model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    return Settings.model_validate(data)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    return application


# ── 1. Completeness: no route escapes the matrix ──────────────────────────────


def test_every_route_is_declared() -> None:
    """The app's routes and ``EXPECTED``'s keys are the same set, both ways."""
    actual = set(ROUTES)
    declared = set(EXPECTED)
    assert actual - declared == set(), "route(s) added with no authz declaration"
    assert declared - actual == set(), "stale authz declaration(s) for deleted route(s)"


# ── 2. The declared guard is the wired guard ──────────────────────────────────


def test_declared_guard_matches_the_wired_guard() -> None:
    mismatched = {
        (method, route.path): (EXPECTED.get((method, route.path)), _wired_guard(route))
        for route in _flatten(create_app().router)
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
        and EXPECTED.get((method, route.path)) != _wired_guard(route)
    }
    assert mismatched == {}


# ── 3a. Unauthenticated → 401 on every non-public route ───────────────────────


@pytest.mark.parametrize(("method", "path"), _NON_PUBLIC, ids=lambda v: str(v))
def test_unauthenticated_caller_is_401(app: FastAPI, method: str, path: str) -> None:
    resp = TestClient(app).request(method, _concrete(path))
    assert resp.status_code == 401, (method, path, resp.status_code)
    assert resp.headers.get("WWW-Authenticate") == "Bearer", (method, path)


# ── 3b. Every role a route does not name → 403 ────────────────────────────────


@pytest.mark.parametrize(("method", "path", "role"), _ROLE_GATED, ids=lambda v: str(v))
def test_disallowed_role_is_403(app: FastAPI, method: str, path: str, role: str) -> None:
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id="u1", role=role)
    resp = TestClient(app).request(method, _concrete(path))
    assert resp.status_code == 403, (method, path, role, resp.status_code)


# ── 3c. The same rejections through the REAL token chain ─────────────────────
#
# 3a and 3b override ``get_auth_context``, so they prove ``require_role`` given a
# correctly-populated AuthContext — they cannot see a break in token decoding
# itself, because the code that builds the context is the code they replace. The
# P6.3 review named that as the gap. These cases use a genuinely minted token and
# no override at all, one representative route per guard class, so the whole
# chain (header → decode → claim extraction → role compare) is exercised.
_REPRESENTATIVE = {
    guard: next((m, p) for m, p in ROUTES if EXPECTED[(m, p)] == guard)
    for guard in (STUDENT, PARENT, TEACHER, SCHOOL_ADMIN, TEACHER_OR_SCHOOL_ADMIN, STAFF)
}
_REAL_TOKEN_CASES = [
    (method, path, role)
    for guard, (method, path) in _REPRESENTATIVE.items()
    for role in sorted(ALL_ROLES - guard)
]


@pytest.mark.parametrize(("method", "path", "role"), _REAL_TOKEN_CASES, ids=lambda v: str(v))
def test_real_token_of_a_disallowed_role_is_403(
    app: FastAPI, settings: Settings, method: str, path: str, role: str
) -> None:
    token = mint_access_token(
        user_id=uuid.uuid4(), settings=settings, app_role=role, provider="email"
    )
    resp = TestClient(app).request(
        method, _concrete(path), headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403, (method, path, role, resp.status_code)


@pytest.mark.parametrize(
    "header",
    [
        "Bearer not-a-jwt",
        "Bearer " + "a.b.c",
        "Basic dXNlcjpwYXNz",
        "",
    ],
)
def test_a_malformed_credential_is_401_not_a_pass(app: FastAPI, header: str) -> None:
    """A token the chain cannot decode must fail closed."""
    method, path = _REPRESENTATIVE[STUDENT]
    resp = TestClient(app).request(method, _concrete(path), headers={"Authorization": header})
    assert resp.status_code == 401, (header, resp.status_code)


def test_the_sweeps_actually_cover_the_surface() -> None:
    """Guard against a silently empty parametrization (P6.2's decoration lesson)."""
    assert len(ROUTES) == len(EXPECTED)
    assert len(_NON_PUBLIC) == len(ROUTES) - 5  # 4 auth entrypoints + /api/health
    assert len(_ROLE_GATED) > 300
    assert len(_REPRESENTATIVE) == 6
    assert len(_REAL_TOKEN_CASES) >= 20
