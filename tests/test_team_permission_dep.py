"""require_team_permission: who may act for which teacher, with what (spec §2.3, §7)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated

import pytest
import sqlalchemy as sa
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import JSONB

from lemely.core.team_permissions import TeamPermission
from lemely.db.models.enums import Role
from lemely.db.models.team import AssistantRole, TeacherMember, TeacherMemberStatus
from lemely.db.teacher_team_repo import (
    TeacherTeamService,
    TeacherTeamStore,
    assistant_has_permission,
)
from lemely.web import deps
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    TeamActor,
    get_assistant_redeem_limiter,
    get_auth_context,
    get_teacher_team_store,
    require_team_permission,
)
from tests.team_db import add_assistant, add_user, emptied_after, team_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.dependencies.models import Dependant
    from sqlalchemy.orm import Session, sessionmaker

_VIEW = require_team_permission(TeamPermission.VIEW_RESULTS)
_MANAGE = require_team_permission(TeamPermission.MANAGE_CLASSES)
_STAFF_VIEW = require_team_permission(
    TeamPermission.VIEW_RESULTS, Role.teacher, Role.school_admin, Role.platform_admin
)


def _body(actor: TeamActor) -> dict[str, str | None]:
    return {
        "actor": str(actor.actor_user_id),
        "lead": str(actor.lead_teacher_user_id),
        "member": str(actor.member_id) if actor.member_id is not None else None,
        "authUser": actor.auth.user_id,
        "authRole": actor.auth.role,
    }


probe = FastAPI()


@probe.get("/view")
def view(actor: Annotated[TeamActor, Depends(_VIEW)]) -> dict[str, str | None]:
    return _body(actor)


@probe.get("/manage")
def manage(actor: Annotated[TeamActor, Depends(_MANAGE)]) -> dict[str, str | None]:
    return _body(actor)


@probe.get("/staff")
def staff(actor: Annotated[TeamActor, Depends(_STAFF_VIEW)]) -> dict[str, str | None]:
    return _body(actor)


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def _call(
    sm: sessionmaker[Session],
    path: str,
    *,
    caller: uuid.UUID,
    role: Role = Role.teacher,
    acting_for: str | list[str] | None = None,
) -> tuple[int, dict[str, object]]:
    probe.dependency_overrides[get_teacher_team_store] = lambda: TeacherTeamStore(sm)
    probe.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(caller), role=role.value
    )
    headers: list[tuple[str, str]] = []
    if isinstance(acting_for, str):
        headers.append((ACTING_TEACHER_HEADER, acting_for))
    elif acting_for is not None:
        headers.extend((ACTING_TEACHER_HEADER, value) for value in acting_for)
    try:
        resp = TestClient(probe).get(path, headers=headers)
    finally:
        probe.dependency_overrides.clear()
    return resp.status_code, resp.json()


def _code(body: dict[str, object]) -> object:
    detail = body["detail"]
    assert isinstance(detail, dict)
    return detail["code"]


def test_lead_without_header_acts_as_self(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher)
    status, body = _call(sm, "/manage", caller=lead)
    assert status == 200
    assert body == {
        "actor": str(lead),
        "lead": str(lead),
        "member": None,
        "authUser": str(lead),
        "authRole": "teacher",
    }


def test_header_naming_self_acts_as_self(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher)
    status, body = _call(sm, "/manage", caller=lead, acting_for=str(lead))
    assert status == 200
    assert body["member"] is None
    assert body["authUser"] == str(lead)


def test_assistant_with_the_permission_acts_as_the_lead(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    status, body = _call(sm, "/view", caller=helper, acting_for=str(lead))
    assert status == 200
    assert body == {
        "actor": str(helper),
        "lead": str(lead),
        "member": str(member),
        "authUser": str(lead),
        "authRole": "teacher",
    }


def test_assistant_without_the_permission_is_403(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.marker)
    status, body = _call(sm, "/manage", caller=helper, acting_for=str(lead))
    assert status == 403
    assert _code(body) == "team_permission_denied"


def test_a_toggle_grants_beyond_the_preset(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(
        sm,
        teacher_id=lead,
        assistant_id=helper,
        role=AssistantRole.viewer,
        permissions={"manage_classes": True},
    )
    assert _call(sm, "/manage", caller=helper, acting_for=str(lead))[0] == 200


def test_a_toggle_revokes_from_the_preset(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(
        sm,
        teacher_id=lead,
        assistant_id=helper,
        role=AssistantRole.co_teacher,
        permissions={"manage_classes": False},
    )
    assert _call(sm, "/manage", caller=helper, acting_for=str(lead))[0] == 403


def test_a_removed_assistant_is_403(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, status=TeacherMemberStatus.removed)
    assert _call(sm, "/view", caller=helper, acting_for=str(lead))[0] == 403


def test_a_stranger_teacher_is_403(sm: sessionmaker[Session]) -> None:
    lead, stranger = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    assert _call(sm, "/view", caller=stranger, acting_for=str(lead))[0] == 403


def test_assisting_one_teacher_gives_nothing_for_another(sm: sessionmaker[Session]) -> None:
    lead, other_lead, helper = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    add_assistant(sm, teacher_id=lead, assistant_id=helper)
    assert _call(sm, "/view", caller=helper, acting_for=str(other_lead))[0] == 403


@pytest.mark.parametrize(
    "header",
    ["not-a-uuid", "", " ", "1; DROP TABLE users", "x" * 5000],
    ids=["text", "empty", "blank", "sql", "huge"],
)
def test_a_malformed_header_is_403_never_500(sm: sessionmaker[Session], header: str) -> None:
    helper = add_user(sm, Role.teacher)
    status, body = _call(sm, "/view", caller=helper, acting_for=header)
    assert status == 403
    assert _code(body) == "team_permission_denied"


def test_several_header_values_are_refused_even_when_one_is_valid(
    sm: sessionmaker[Session],
) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper)
    both = [str(lead), str(helper)]
    assert _call(sm, "/view", caller=helper, acting_for=both)[0] == 403
    assert _call(sm, "/view", caller=helper, acting_for=list(reversed(both)))[0] == 403
    assert _call(sm, "/view", caller=helper, acting_for=f"{lead}, {helper}")[0] == 403


def test_an_unknown_lead_is_indistinguishable_from_a_stranger(
    sm: sessionmaker[Session],
) -> None:
    real_lead, stranger = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    ghost = uuid.uuid4()
    existing = _call(sm, "/view", caller=stranger, acting_for=str(real_lead))
    missing = _call(sm, "/view", caller=stranger, acting_for=str(ghost))
    assert existing == missing
    assert missing[0] == 403
    assert _code(missing[1]) == "team_permission_denied"


@pytest.mark.parametrize("role", [Role.student, Role.parent])
def test_a_student_or_parent_cannot_borrow_a_teacher_identity(
    sm: sessionmaker[Session], role: Role
) -> None:
    lead, caller = add_user(sm, Role.teacher), add_user(sm, role)
    # Even a hostile assistant row naming a non-teacher must not matter: the role
    # guard runs on the real caller first, with or without the header.
    add_assistant(sm, teacher_id=lead, assistant_id=caller)
    assert _call(sm, "/view", caller=caller, role=role)[0] == 403
    assert _call(sm, "/view", caller=caller, role=role, acting_for=str(lead))[0] == 403
    assert _call(sm, "/view", caller=caller, role=role, acting_for=str(caller))[0] == 403


def test_a_school_admin_may_not_act_for_a_teacher(sm: sessionmaker[Session]) -> None:
    lead, admin = add_user(sm, Role.teacher), add_user(sm, Role.school_admin)
    # Same hostile row: a school admin with an assistant row still is not a teacher.
    add_assistant(sm, teacher_id=lead, assistant_id=admin)
    status, body = _call(sm, "/staff", caller=admin, role=Role.school_admin, acting_for=str(lead))
    assert status == 403
    assert _code(body) == "team_permission_denied"


def test_a_platform_admin_may_not_act_for_a_teacher(sm: sessionmaker[Session]) -> None:
    lead, admin = add_user(sm, Role.teacher), add_user(sm, Role.platform_admin)
    status, _ = _call(sm, "/staff", caller=admin, role=Role.platform_admin, acting_for=str(lead))
    assert status == 403


def test_a_school_admin_without_header_keeps_their_own_role(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.school_admin)
    status, body = _call(sm, "/staff", caller=admin, role=Role.school_admin)
    assert status == 200
    assert body["authRole"] == "school_admin"
    assert body["authUser"] == str(admin)
    assert body["member"] is None


def test_a_school_admin_naming_self_keeps_their_own_role(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.school_admin)
    status, body = _call(sm, "/staff", caller=admin, role=Role.school_admin, acting_for=str(admin))
    assert status == 200
    assert body["authRole"] == "school_admin"


def test_the_role_guard_still_runs_first(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    assert _call(sm, "/view", caller=student, role=Role.student)[0] == 403
    assert _call(sm, "/staff", caller=student, role=Role.student)[0] == 403


def test_assistant_has_permission_is_the_shared_rule(sm: sessionmaker[Session]) -> None:
    lead, viewer, marker, gone = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    viewer_row = add_assistant(sm, teacher_id=lead, assistant_id=viewer, role=AssistantRole.viewer)
    add_assistant(
        sm,
        teacher_id=lead,
        assistant_id=marker,
        role=AssistantRole.marker,
        permissions={"mark": False},
    )
    add_assistant(sm, teacher_id=lead, assistant_id=gone, status=TeacherMemberStatus.removed)
    with sm() as session:
        member = assistant_has_permission(session, viewer, lead, TeamPermission.VIEW_RESULTS)
        assert member is not None
        assert member.id == viewer_row
        # A viewer cannot mark: Phase 04's estimate route refuses on this.
        assert assistant_has_permission(session, viewer, lead, TeamPermission.MARK) is None
        assert assistant_has_permission(session, marker, lead, TeamPermission.MARK) is None
        assert assistant_has_permission(session, marker, lead, TeamPermission.REGRADE) is not None
        assert assistant_has_permission(session, gone, lead, TeamPermission.VIEW_RESULTS) is None
        assert assistant_has_permission(session, lead, lead, TeamPermission.VIEW_RESULTS) is None
        service_member = TeacherTeamService(session).assistant_has_permission(
            viewer, lead, TeamPermission.VIEW_USAGE
        )
        assert service_member is not None
        assert service_member.id == viewer_row
        assert (
            TeacherTeamService(session).assistant_has_permission(
                viewer, lead, TeamPermission.MANAGE_CLASSES
            )
            is None
        )


def test_an_unreadable_row_fails_closed(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    # Toggles are validated on write; a row that slipped past (a manual edit) must
    # deny, not answer 500.
    add_assistant(
        sm,
        teacher_id=lead,
        assistant_id=helper,
        role=AssistantRole.co_teacher,
        permissions={"manage_billing": True},
    )
    status, body = _call(sm, "/view", caller=helper, acting_for=str(lead))
    assert status == 403
    assert _code(body) == "team_permission_denied"
    with sm() as session:
        assert assistant_has_permission(session, helper, lead, TeamPermission.VIEW_RESULTS) is None


def _store_raw_permissions(sm: sessionmaker[Session], member_id: uuid.UUID, raw_json: str) -> None:
    """Write ``raw_json`` straight into ``permissions``, as a hand edit or a bad import could."""
    with sm.begin() as session:
        session.execute(
            sa.update(TeacherMember)
            .where(TeacherMember.id == member_id)
            .values(permissions=sa.cast(sa.literal(raw_json), JSONB))
        )


@pytest.mark.parametrize(
    "raw_json",
    ["[]", '"x"', "5", "true", "null", "[1, 2]", '{"mark": "yes"}', '{"mark": 1}'],
    ids=["empty-list", "string", "number", "bool", "json-null", "list", "str-toggle", "int-toggle"],
)
def test_malformed_stored_toggles_fail_closed_with_the_uniform_403(
    sm: sessionmaker[Session], raw_json: str
) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.co_teacher)
    _store_raw_permissions(sm, member, raw_json)
    status, body = _call(sm, "/view", caller=helper, acting_for=str(lead))
    assert status == 403
    assert _code(body) == "team_permission_denied"
    with sm() as session:
        for perm in TeamPermission:
            assert assistant_has_permission(session, helper, lead, perm) is None


@pytest.mark.parametrize("lead_role", [Role.student, Role.parent, Role.school_admin])
def test_an_assistant_row_under_a_lead_who_is_no_longer_a_teacher_is_403(
    sm: sessionmaker[Session], lead_role: Role
) -> None:
    """The row is hand-seeded: nothing in the schema stops a lead's role from changing."""
    lead, helper = add_user(sm, lead_role), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.co_teacher)
    status, body = _call(sm, "/view", caller=helper, acting_for=str(lead))
    assert status == 403
    assert _code(body) == "team_permission_denied"
    with sm() as session:
        assert assistant_has_permission(session, helper, lead, TeamPermission.VIEW_RESULTS) is None


def test_a_lead_who_is_a_teacher_still_passes_the_role_recheck(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    assert _call(sm, "/view", caller=helper, acting_for=str(lead))[0] == 200


def test_a_padded_acting_header_is_accepted(sm: sessionmaker[Session]) -> None:
    """Servers differ on trimming header values; padding must not change the answer."""
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    status, body = _call(sm, "/view", caller=helper, acting_for=f"  {lead}\t")
    assert status == 200
    assert body["member"] == str(member)
    assert _call(sm, "/manage", caller=lead, acting_for=f" {lead} ")[0] == 200


def test_billing_and_seat_management_are_not_team_permissions() -> None:
    names = {p.value for p in TeamPermission}
    assert not {"billing", "manage_billing", "manage_seats", "manage_assistants"} & names
    assert not any(word in name for name in names for word in ("billing", "seat", "plan", "pay"))


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk(sub)


def _wired_roles(path: str) -> frozenset[str]:
    """Read the role set the way ``tests/test_authz_matrix_complete.py`` does."""
    route = next(r for r in probe.routes if isinstance(r, APIRoute) and r.path == path)
    roles: set[str] | None = None
    for dependant in _walk(route.dependant):
        call = dependant.call
        if call is None or getattr(call, "__name__", "") != "_guard" or not call.__closure__:
            continue
        cells = dict(zip(call.__code__.co_freevars, call.__closure__, strict=True))
        allowed = cells["allowed_values"].cell_contents
        roles = set(allowed) if roles is None else roles & set(allowed)
    assert roles is not None
    return frozenset(roles)


def test_the_wired_role_set_stays_visible_to_the_authz_matrix() -> None:
    assert _wired_roles("/view") == {"teacher"}
    assert _wired_roles("/staff") == {"teacher", "school_admin", "platform_admin"}


def test_the_guard_carries_its_permission_and_role_guard() -> None:
    cells = dict(zip(_MANAGE.__code__.co_freevars, _MANAGE.__closure__ or (), strict=True))
    assert _MANAGE.__name__ == "_team_guard"
    assert cells["perm"].cell_contents is TeamPermission.MANAGE_CLASSES


def test_team_actor_is_frozen() -> None:
    lead = uuid.uuid4()
    actor = TeamActor(
        actor_user_id=lead,
        lead_teacher_user_id=lead,
        member_id=None,
        auth=AuthContext(user_id=str(lead), role="teacher"),
    )
    with pytest.raises(AttributeError):
        actor.member_id = uuid.uuid4()  # type: ignore[misc]


def test_header_is_documented_in_the_openapi_schema() -> None:
    params = probe.openapi()["paths"]["/view"]["get"]["parameters"]
    assert [p["name"] for p in params] == [ACTING_TEACHER_HEADER.lower()] or [
        p["name"] for p in params
    ] == [ACTING_TEACHER_HEADER]


def test_store_and_redeem_limiter_are_cached_singletons_cleared_by_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "get_sessionmaker", lambda _settings: object())
    deps.get_teacher_team_store.cache_clear()
    deps.get_assistant_redeem_limiter.cache_clear()
    try:
        store = get_teacher_team_store()
        limiter = get_assistant_redeem_limiter()
        assert store is get_teacher_team_store()
        assert limiter is get_assistant_redeem_limiter()
        user = str(uuid.uuid4())
        assert [limiter.allow(user) for _ in range(11)] == [True] * 10 + [False]
        assert limiter.allow(str(uuid.uuid4())) is True
        deps.reset_singletons()
        assert get_teacher_team_store() is not store
        assert get_assistant_redeem_limiter() is not limiter
        # A fresh limiter has forgotten the exhausted user.
        assert get_assistant_redeem_limiter().allow(user) is True
    finally:
        deps.get_teacher_team_store.cache_clear()
        deps.get_assistant_redeem_limiter.cache_clear()


def test_reset_singletons_also_clears_the_invite_preview_limiters() -> None:
    from lemely.web.deps_invites import get_invite_preview_limiters

    first = get_invite_preview_limiters()
    assert first is get_invite_preview_limiters()
    deps.reset_singletons()
    assert get_invite_preview_limiters() is not first
