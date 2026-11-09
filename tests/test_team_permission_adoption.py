"""Which existing routes an assistant may use, and under which permission (spec §2.3, §3).

The registry below is the reviewed endpoint → permission map from the Phase 03 plan.
``test_adopted_routes_are_exactly_the_registry`` reads the permission actually wired
into each route (the ``perm`` cell of ``require_team_permission``'s ``_team_guard``)
and requires the two to be equal. A route that gains or loses the guard, or changes
its permission, fails here and must be changed twice, deliberately.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.team_permissions import TeamPermission
from lemely.web import create_app
from tests.test_authz_matrix_complete import _flatten, _walk

if TYPE_CHECKING:
    from fastapi.routing import APIRoute

VIEW = TeamPermission.VIEW_RESULTS
MARK = TeamPermission.MARK
REGRADE = TeamPermission.REGRADE
QUIZ = TeamPermission.GENERATE_QUIZ
CLASSES = TeamPermission.MANAGE_CLASSES
STUDENTS = TeamPermission.MANAGE_STUDENTS

ADOPTED: dict[tuple[str, str], TeamPermission] = {
    # classes.py
    ("GET", "/api/teacher/classes"): VIEW,
    ("GET", "/api/classes/{class_id}"): VIEW,
    ("GET", "/api/classes/{class_id}/analytics"): VIEW,
    ("POST", "/api/classes"): CLASSES,
    ("PATCH", "/api/classes/{class_id}"): CLASSES,
    ("DELETE", "/api/classes/{class_id}"): CLASSES,
    ("GET", "/api/classes/{class_id}/roster"): VIEW,
    ("POST", "/api/classes/{class_id}/enroll"): STUDENTS,
    ("DELETE", "/api/classes/{class_id}/students/{student_id}"): STUDENTS,
    ("GET", "/api/classes/{class_id}/papers"): VIEW,
    ("POST", "/api/classes/{class_id}/papers/{attempt_id}/unshare"): CLASSES,
    ("DELETE", "/api/classes/{class_id}/papers/{attempt_id}/unshare"): CLASSES,
    ("POST", "/api/school/classes/{class_id}/invite-code"): STUDENTS,
    # announcements.py
    ("GET", "/api/teacher/announcements"): VIEW,
    ("POST", "/api/teacher/announcements"): CLASSES,
    ("DELETE", "/api/teacher/announcements/{announcement_id}"): CLASSES,
}

LEAD_ONLY_PREFIXES = (
    "/api/teacher/team",
    "/api/tutor/",
    "/api/tutoring/",
    "/api/billing",
    "/billing",
    "/api/admin",
    "/webhooks",
)
"""Surfaces that must never take the team guard (spec §2.3, §7; tutoring is sub-project B)."""


def _team_permission(route: APIRoute) -> TeamPermission | None:
    found: TeamPermission | None = None
    for dependant in _walk(route.dependant):
        call = dependant.call
        if call is None or getattr(call, "__name__", "") != "_team_guard":
            continue
        cells = dict(zip(call.__code__.co_freevars, call.__closure__ or (), strict=True))
        permission = cells["perm"].cell_contents
        assert found in (None, permission), f"{route.path} carries two team permissions"
        found = permission
    return found


def _wired() -> dict[tuple[str, str], TeamPermission | None]:
    wired: dict[tuple[str, str], TeamPermission | None] = {}
    for route in _flatten(create_app()):
        permission = _team_permission(route)
        for method in sorted(route.methods or ()):
            wired[(method, route.path)] = permission
    return wired


def test_registry_names_only_real_routes() -> None:
    assert set(ADOPTED) <= set(_wired())


def test_adopted_routes_are_exactly_the_registry() -> None:
    adopted = {key: perm for key, perm in _wired().items() if perm is not None}
    assert adopted == ADOPTED


def test_lead_only_surfaces_never_take_the_team_guard() -> None:
    for (method, path), permission in _wired().items():
        if path.startswith(LEAD_ONLY_PREFIXES):
            assert permission is None, (method, path)
