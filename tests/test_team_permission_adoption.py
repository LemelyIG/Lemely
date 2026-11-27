"""Which existing routes an assistant may use, and under which permission (spec §2.3, §3).

The registry below is the reviewed endpoint → permission map from the Phase 03 plan.
``test_adopted_routes_are_exactly_the_registry`` reads the permission actually wired
into each route (the ``perm`` cell of ``require_team_permission``'s ``_team_guard``)
and requires the two to be equal. A route that gains or loses the guard, or changes
its permission, fails here and must be changed twice, deliberately.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, get_args, get_origin, get_type_hints

from fastapi import APIRouter, Depends, FastAPI

from lemely.core.team_permissions import TeamPermission
from lemely.db.models.enums import Role
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    TeamActor,
    get_auth_context,
    require_role,
    require_team_permission,
)
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
    # teacher.py
    ("POST", "/api/papers/upload"): MARK,
    ("GET", "/api/papers"): VIEW,
    ("POST", "/api/papers/{paper_id}/regrade"): REGRADE,
    ("GET", "/api/papers/deleted"): VIEW,
    ("DELETE", "/api/papers/{paper_id}"): CLASSES,
    ("POST", "/api/papers/{paper_id}/restore"): CLASSES,
    ("GET", "/api/papers/{paper_id}"): VIEW,
    ("GET", "/api/papers/{paper_id}/preview"): VIEW,
    ("GET", "/api/grading/queue"): VIEW,
    ("GET", "/api/quizzes/pools"): QUIZ,
    ("POST", "/api/quizzes/preview"): QUIZ,
    ("POST", "/api/quizzes/generate"): QUIZ,
    ("GET", "/api/teacher/overview"): VIEW,
    ("GET", "/api/teacher/students/{student_id}"): VIEW,
    ("GET", "/api/teacher/at-risk"): VIEW,
    ("POST", "/api/teacher/at-risk/{student_id}/acknowledge"): STUDENTS,
    ("DELETE", "/api/teacher/at-risk/{student_id}/acknowledge/{reason}"): STUDENTS,
    # quiz.py
    ("POST", "/api/teacher/quizzes"): QUIZ,
    ("GET", "/api/teacher/quizzes"): VIEW,
    ("GET", "/api/teacher/quizzes/pool-count"): VIEW,
    ("GET", "/api/teacher/quizzes/{quiz_id}"): VIEW,
    ("PATCH", "/api/teacher/quizzes/{quiz_id}"): QUIZ,
    ("POST", "/api/teacher/quizzes/{quiz_id}/status"): QUIZ,
    ("POST", "/api/teacher/quizzes/{quiz_id}/questions/generate"): QUIZ,
    ("DELETE", "/api/teacher/quizzes/{quiz_id}/questions/{question_ref}"): QUIZ,
    ("POST", "/api/teacher/quizzes/{quiz_id}/assignments"): QUIZ,
    ("GET", "/api/teacher/quizzes/{quiz_id}/assignments"): VIEW,
    ("DELETE", "/api/teacher/quizzes/{quiz_id}/assignments/{assignment_id}"): QUIZ,
    ("GET", "/api/teacher/quizzes/{quiz_id}/assignments/{assignment_id}/results"): VIEW,
    # review.py
    ("GET", "/api/teacher/review"): VIEW,
    ("GET", "/api/teacher/review/{item_id}"): VIEW,
    ("GET", "/api/teacher/review/{item_id}/crop"): VIEW,
    ("GET", "/api/teacher/review/{item_id}/page"): VIEW,
    ("POST", "/api/teacher/review/bulk-approve"): MARK,
    ("POST", "/api/teacher/review/{item_id}/resolve"): MARK,
    ("POST", "/api/teacher/review/{item_id}/dismiss"): MARK,
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


def test_caller_agnostic_routes_stay_unadopted() -> None:
    wired = _wired()
    for key in (("GET", "/api/schemes"), ("POST", "/api/schemes"), ("GET", "/api/quizzes/topics")):
        assert wired[key] is None, key


# Module level: this file's annotations are strings, resolved against module globals by FastAPI.
_PROBE_GUARD = require_team_permission(TeamPermission.VIEW_RESULTS, Role.teacher)


def _routes_without_actor_parameter(routes: list[APIRoute]) -> list[tuple[str, str]]:
    """Guarded routes whose handler never receives the guard's result as a ``TeamActor``.

    A guard parked in ``dependencies=[...]`` still runs, but the handler would keep reading a
    separate ``require_role`` auth: it would act as the assistant, not as the lead.
    """
    missing: list[tuple[str, str]] = []
    for route in routes:
        if _team_permission(route) is None:
            continue
        receiving = {
            dependant.name
            for dependant in route.dependant.dependencies
            if getattr(dependant.call, "__name__", "") == "_team_guard" and dependant.name
        }
        hints = get_type_hints(route.endpoint, include_extras=True)
        typed = {
            name
            for name in receiving
            if (hint := hints.get(name)) is not None
            and get_origin(hint) is Annotated
            and get_args(hint)[0] is TeamActor
        }
        if not typed:
            missing.append((",".join(sorted(route.methods or ())), route.path))
    return missing


def test_every_adopted_handler_receives_the_guards_actor() -> None:
    assert _routes_without_actor_parameter(_flatten(create_app())) == []


def test_a_guard_set_in_dependencies_without_a_team_actor_parameter_is_caught() -> None:
    """Mutation proof: the check goes red for each way a handler can ignore the guard."""
    router = APIRouter()

    @router.get("/parked", dependencies=[Depends(_PROBE_GUARD)])
    def parked(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> dict[str, str]:
        return {"user": auth.user_id}

    @router.get("/wrong-type")
    def wrong_type(actor: Annotated[AuthContext, Depends(_PROBE_GUARD)]) -> dict[str, str]:
        return {"user": actor.user_id}

    @router.get("/second-role-guard")
    def second_role_guard(
        actor: Annotated[TeamActor, Depends(_PROBE_GUARD)],
        auth: Annotated[AuthContext, Depends(require_role(Role.teacher))],
    ) -> dict[str, str]:
        return {"user": auth.user_id, "lead": str(actor.lead_teacher_user_id)}

    @router.get("/good")
    def good(actor: Annotated[TeamActor, Depends(_PROBE_GUARD)]) -> dict[str, str]:
        return {"lead": str(actor.lead_teacher_user_id)}

    app = FastAPI()
    app.include_router(router)
    missing = _routes_without_actor_parameter(_flatten(app))
    assert {("GET", "/parked"), ("GET", "/wrong-type")} <= set(missing)
    assert ("GET", "/good") not in missing
    assert len(_flatten(app)) == 4  # all four probe routes were really registered
    # A handler that takes the actor but still reads a second role guard passes this check;
    # it is the behaviour tests (assistant records against the lead) that catch that mutation.
    assert ("GET", "/second-role-guard") not in missing
