"""HTTP tests for /api/teacher/team: lead-only management, IDOR, rate limit (§2.2, §2.3, §7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lemely.db.models import Invite
from lemely.db.models.enums import Role
from lemely.db.models.team import AssistantRole, TeacherMember, TeacherMemberStatus
from lemely.db.models.usage import GrantKind, UsageEntryKind
from lemely.db.teacher_team_repo import (
    MAX_LIVE_ASSISTANT_INVITES,
    AssistantInviteLimitError,
    AssistantInviteNotFound,
    AssistantInviteRedeemed,
    InvalidCap,
    InvalidInviteExpiry,
    InvalidPermissions,
    InvalidScope,
    NoFreeSeat,
    NotATeacher,
    TeacherTeamService,
    TeacherTeamStore,
    TeamError,
    TeamMemberNotFound,
    TeamStateError,
)
from lemely.web.app import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_assistant_redeem_limiter,
    get_auth_context,
    get_teacher_team_store,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.team_http import team_error_to_http
from tests.team_db import (
    add_assistant,
    add_entry,
    add_grant,
    add_seat,
    add_subject,
    add_teacher_plan,
    add_user,
    emptied_after,
    set_remaining,
    team_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

BASE = "/api/teacher/team"
# The router reads the real clock (month window, grant validity), so seed usage at it.
NOW_REAL = datetime.now(UTC)


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def client(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    role: Role = Role.teacher,
    *,
    limiter: SlidingWindowLimiter | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_teacher_team_store] = lambda: TeacherTeamStore(sm)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(user), role=role.value
    )
    fresh = limiter or SlidingWindowLimiter(limit=1000, window_seconds=60.0, clock=lambda: 0.0)
    app.dependency_overrides[get_assistant_redeem_limiter] = lambda: fresh
    return TestClient(app)


# ── seats ─────────────────────────────────────────────────────────────────────


def test_list_seats_and_capacity(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    student = add_user(sm, display_name="Omar")
    add_teacher_plan(sm, teacher, included_seats=2, extra_seats=1)
    seat = add_seat(sm, teacher_id=teacher, student_id=student, subjects=["0580"])
    credits = add_grant(sm, owner_id=teacher, kind=GrantKind.credit_pack, units=1000, at=NOW_REAL)
    add_entry(
        sm, grant_id=credits, member_id=seat, kind=UsageEntryKind.settle, units=-40, at=NOW_REAL
    )
    allowance = add_grant(
        sm,
        owner_id=student,
        kind=GrantKind.seat_allowance,
        units=100,
        at=NOW_REAL,
        teacher_member_id=seat,
    )
    set_remaining(sm, allowance, 75)
    c = client(sm, teacher)
    seats = c.get(f"{BASE}/seats").json()["seats"]
    assert [(s["memberId"], s["studentName"], s["scopeSubjects"]) for s in seats] == [
        (str(seat), "Omar", ["0580"])
    ]
    assert seats[0]["kind"] == "student_seat"
    assert seats[0]["capUsedUnits"] == 40
    assert seats[0]["meterFraction"] == pytest.approx(0.25)
    assert seats[0]["joinedAt"] is not None
    assert "email" not in seats[0]
    assert c.get(f"{BASE}/capacity").json() == {"capacity": 3, "used": 1, "free": 2}


def test_seat_wire_fields_are_exactly_the_frontend_contract(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_seat(sm, teacher_id=teacher, student_id=student)
    [seat] = client(sm, teacher).get(f"{BASE}/seats").json()["seats"]
    assert set(seat) == {
        "kind",
        "memberId",
        "studentId",
        "studentName",
        "status",
        "leavesAt",
        "scopeSubjects",
        "scopeActions",
        "capUnits",
        "capPeriod",
        "capUsedUnits",
        "meterFraction",
        "joinedAt",
    }
    assert seat["studentName"] == "Student"  # no display name: neutral fallback, never the email
    assert seat["meterFraction"] is None
    assert seat["capUnits"] is None
    assert seat["capPeriod"] == "month"


def test_capacity_without_a_plan_is_zero_and_never_negative(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_seat(sm, teacher_id=teacher, student_id=student)
    assert client(sm, teacher).get(f"{BASE}/capacity").json() == {
        "capacity": 0,
        "used": 1,
        "free": 0,
    }


def test_leaving_seats_still_count_as_used(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=3)
    add_seat(sm, teacher_id=teacher, student_id=s1)
    add_seat(
        sm,
        teacher_id=teacher,
        student_id=s2,
        status=TeacherMemberStatus.leaving,
        leaves_at=NOW_REAL + timedelta(days=5),
    )
    c = client(sm, teacher)
    assert c.get(f"{BASE}/capacity").json() == {"capacity": 3, "used": 2, "free": 1}
    statuses = [s["status"] for s in c.get(f"{BASE}/seats").json()["seats"]]
    assert statuses == ["active", "leaving"]


def test_set_scope_including_study_plan(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_subject(sm, "0580")
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    resp = client(sm, teacher).put(
        f"{BASE}/seats/{seat}/scope",
        json={"subjects": ["0580"], "actions": ["mark_paper", "study_plan"]},
    )
    assert resp.status_code == 200
    assert resp.json()["scopeActions"] == ["mark_paper", "study_plan"]


def test_set_scope_with_an_unknown_action_is_422(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    resp = client(sm, teacher).put(
        f"{BASE}/seats/{seat}/scope", json={"subjects": [], "actions": ["buy_seats"]}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_scope"
    assert "buy_seats" not in resp.text  # the refused value is never echoed


def test_set_scope_with_an_unknown_subject_is_422(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    resp = client(sm, teacher).put(
        f"{BASE}/seats/{seat}/scope", json={"subjects": ["NOPE"], "actions": ["mark_paper"]}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_scope"


def test_remove_seat_sets_leaving(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    resp = client(sm, teacher).delete(f"{BASE}/seats/{seat}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "leaving"
    assert resp.json()["leavesAt"] is not None


def test_remove_seat_is_idempotent_and_keeps_the_original_leave_date(
    sm: sessionmaker[Session],
) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    c = client(sm, teacher)
    first = c.delete(f"{BASE}/seats/{seat}").json()
    second = c.delete(f"{BASE}/seats/{seat}")
    assert second.status_code == 200
    assert second.json()["leavesAt"] == first["leavesAt"]


def test_set_cap_on_a_seat_and_an_assistant(sm: sessionmaker[Session]) -> None:
    teacher, student, helper = add_user(sm, Role.teacher), add_user(sm), add_user(sm, Role.teacher)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    c = client(sm, teacher)
    for member, kind in ((seat, "student_seat"), (assistant, "assistant")):
        resp = c.put(f"{BASE}/members/{member}/cap", json={"capUnits": 250, "capPeriod": "total"})
        assert resp.status_code == 200
        body = resp.json()
        assert (body["kind"], body["memberId"]) == (kind, str(member))
        assert (body["capUnits"], body["capPeriod"], body["capUsedUnits"]) == (250, "total", 0)
    assert c.put(f"{BASE}/members/{seat}/cap", json={"capUnits": -1}).status_code == 422


def test_set_cap_accepts_zero_and_clears_with_null(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    c = client(sm, teacher)
    zero = c.put(f"{BASE}/members/{seat}/cap", json={"capUnits": 0, "capPeriod": "month"})
    assert (zero.status_code, zero.json()["capUnits"]) == (200, 0)
    cleared = c.put(f"{BASE}/members/{seat}/cap", json={"capUnits": None, "capPeriod": "month"})
    assert (cleared.status_code, cleared.json()["capUnits"]) == (200, None)


def test_set_cap_reports_use_in_the_new_window(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    credits = add_grant(sm, owner_id=teacher, kind=GrantKind.credit_pack, units=1000, at=NOW_REAL)
    add_entry(
        sm, grant_id=credits, member_id=seat, kind=UsageEntryKind.settle, units=-15, at=NOW_REAL
    )
    # A line from ~3 months ago: outside any month window, inside a "total" one.
    add_entry(
        sm,
        grant_id=credits,
        member_id=seat,
        kind=UsageEntryKind.settle,
        units=-20,
        at=NOW_REAL - timedelta(days=90),
    )
    c = client(sm, teacher)
    month = c.put(f"{BASE}/members/{seat}/cap", json={"capUnits": 500, "capPeriod": "month"})
    total = c.put(f"{BASE}/members/{seat}/cap", json={"capUnits": 500, "capPeriod": "total"})
    assert month.json()["capUsedUnits"] == 15
    assert total.json()["capUsedUnits"] == 35


@pytest.mark.parametrize(
    "body",
    [
        {"capUnits": 1, "capPeriod": "weekly"},
        {"capUnits": "many"},
        {"capUnits": 1, "unexpected": True},
    ],
)
def test_set_cap_rejects_malformed_bodies(
    sm: sessionmaker[Session], body: dict[str, object]
) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    assert client(sm, teacher).put(f"{BASE}/members/{seat}/cap", json=body).status_code == 422


# ── IDOR: another teacher's members are invisible ────────────────────────────


def test_another_teachers_members_are_404(sm: sessionmaker[Session]) -> None:
    owner, intruder = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    student, helper = add_user(sm), add_user(sm, Role.teacher)
    add_subject(sm, "0580")
    seat = add_seat(sm, teacher_id=owner, student_id=student)
    assistant = add_assistant(sm, teacher_id=owner, assistant_id=helper)
    c = client(sm, intruder)
    scope = {"subjects": ["0580"], "actions": ["mark_paper"]}
    assert c.put(f"{BASE}/seats/{seat}/scope", json=scope).status_code == 404
    assert c.delete(f"{BASE}/seats/{seat}").status_code == 404
    assert c.put(f"{BASE}/members/{seat}/cap", json={"capUnits": 1}).status_code == 404
    assert c.put(f"{BASE}/members/{assistant}/cap", json={"capUnits": 1}).status_code == 404
    assert c.patch(f"{BASE}/assistants/{assistant}", json={"role": "viewer"}).status_code == 404
    assert c.delete(f"{BASE}/assistants/{assistant}").status_code == 404
    assert c.get(f"{BASE}/seats").json() == {"seats": []}
    assert c.get(f"{BASE}/assistants").json() == {"assistants": []}
    with sm() as session:
        member = TeacherTeamService(session).assistant_membership(helper, owner)
        assert member is not None
        assert member.role_preset is AssistantRole.co_teacher
        rows = list(
            session.scalars(select(TeacherMember).where(TeacherMember.id.in_([seat, assistant])))
        )
        assert {(r.cap_units, r.status) for r in rows} == {(None, TeacherMemberStatus.active)}


def test_another_teachers_404_is_the_same_as_an_unknown_id(sm: sessionmaker[Session]) -> None:
    """A stranger's member and a made-up id answer byte-for-byte alike: no probing."""
    owner, intruder, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=owner, student_id=student)
    c = client(sm, intruder)
    theirs = c.delete(f"{BASE}/seats/{seat}")
    unknown = c.delete(f"{BASE}/seats/{uuid.uuid4()}")
    assert (theirs.status_code, theirs.json()) == (unknown.status_code, unknown.json())
    assert str(seat) not in theirs.text


def test_a_malformed_member_id_is_404(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    assert client(sm, teacher).delete(f"{BASE}/seats/not-a-uuid").status_code == 404


def test_seat_routes_do_not_accept_assistant_ids_and_vice_versa(sm: sessionmaker[Session]) -> None:
    teacher, student, helper = add_user(sm, Role.teacher), add_user(sm), add_user(sm, Role.teacher)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    c = client(sm, teacher)
    assert c.delete(f"{BASE}/seats/{assistant}").status_code == 404
    assert c.delete(f"{BASE}/assistants/{seat}").status_code == 404
    assert c.patch(f"{BASE}/assistants/{seat}", json={"role": "viewer"}).status_code == 404
    scope = {"subjects": [], "actions": ["mark_paper"]}
    assert c.put(f"{BASE}/seats/{assistant}/scope", json=scope).status_code == 404


def test_a_removed_member_is_gone_to_every_route(sm: sessionmaker[Session]) -> None:
    teacher, student, helper = add_user(sm, Role.teacher), add_user(sm), add_user(sm, Role.teacher)
    seat = add_seat(sm, teacher_id=teacher, student_id=student, status=TeacherMemberStatus.removed)
    assistant = add_assistant(
        sm, teacher_id=teacher, assistant_id=helper, status=TeacherMemberStatus.removed
    )
    c = client(sm, teacher)
    assert c.put(f"{BASE}/members/{seat}/cap", json={"capUnits": 1}).status_code == 404
    assert c.put(f"{BASE}/members/{assistant}/cap", json={"capUnits": 1}).status_code == 404
    assert c.delete(f"{BASE}/seats/{seat}").status_code == 404
    assert c.delete(f"{BASE}/assistants/{assistant}").status_code == 404


# ── assistants never reach seat or assistant management of their lead ────────


def _every_team_request(
    seat: uuid.UUID, assistant: uuid.UUID, invite: uuid.UUID
) -> list[tuple[str, str, dict[str, object] | None]]:
    """One request per team route, 13 in all (the authz matrix's 13)."""
    return [
        ("GET", f"{BASE}/seats", None),
        ("GET", f"{BASE}/capacity", None),
        ("PUT", f"{BASE}/seats/{seat}/scope", {"subjects": [], "actions": ["mark_paper"]}),
        ("DELETE", f"{BASE}/seats/{seat}", None),
        ("PUT", f"{BASE}/members/{seat}/cap", {"capUnits": 1}),
        ("GET", f"{BASE}/assistants", None),
        ("POST", f"{BASE}/assistants/invites", {"role": "viewer"}),
        ("GET", f"{BASE}/invites", None),
        ("DELETE", f"{BASE}/invites/{invite}", None),
        ("POST", f"{BASE}/assistants/redeem", {"code": "NOSUCHCODE"}),
        ("PATCH", f"{BASE}/assistants/{assistant}", {"role": "viewer"}),
        ("DELETE", f"{BASE}/assistants/{assistant}", None),
        ("GET", f"{BASE}/memberships", None),
    ]


def test_an_assistant_sending_the_acting_header_gets_403_on_every_team_route(
    sm: sessionmaker[Session],
) -> None:
    lead, helper, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, lead, included_seats=3)
    seat = add_seat(sm, teacher_id=lead, student_id=student)
    assistant = add_assistant(
        sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.co_teacher
    )
    invite = uuid.UUID(
        client(sm, lead)
        .post(f"{BASE}/assistants/invites", json={"role": "viewer"})
        .json()["inviteId"]
    )
    requests = _every_team_request(seat, assistant, invite)
    assert len(requests) == 13
    c = client(sm, helper)
    for method, path, body in requests:
        resp = c.request(method, path, json=body, headers={ACTING_TEACHER_HEADER: str(lead)})
        assert resp.status_code == 403, (method, path, resp.text)
        assert resp.json()["detail"]["code"] == "team_lead_only"
        assert str(lead) not in resp.text
    with sm() as session:
        # Nothing changed: the lead's seat, assistant and invite are all as they were.
        team = TeacherTeamService(session)
        assert [(s.id, s.status, s.cap_units) for s in team.list_seats(lead)] == [
            (seat, TeacherMemberStatus.active, None)
        ]
        assert [a.id for a in team.list_assistants(lead)] == [assistant]
        assert [i.id for i in team.list_assistant_invites(lead, now=NOW_REAL)] == [invite]
        assert session.scalar(select(func.count()).select_from(Invite)) == 1


@pytest.mark.parametrize(
    "header_value",
    [str(uuid.uuid4()), "not-a-uuid", "", " "],
)
def test_any_acting_header_naming_someone_else_is_refused_not_just_a_real_lead(
    sm: sessionmaker[Session], header_value: str
) -> None:
    teacher = add_user(sm, Role.teacher)
    resp = client(sm, teacher).get(f"{BASE}/seats", headers={ACTING_TEACHER_HEADER: header_value})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_lead_only"


def test_a_repeated_acting_header_is_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    resp = client(sm, teacher).get(
        f"{BASE}/seats",
        headers=[(ACTING_TEACHER_HEADER, str(teacher)), (ACTING_TEACHER_HEADER, str(teacher))],
    )
    assert resp.status_code == 403


def test_a_header_naming_the_caller_is_just_the_callers_own_team(sm: sessionmaker[Session]) -> None:
    lead, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=lead, student_id=student)
    resp = client(sm, lead).get(f"{BASE}/seats", headers={ACTING_TEACHER_HEADER: str(lead)})
    assert resp.status_code == 200
    assert [s["memberId"] for s in resp.json()["seats"]] == [str(seat)]


def test_a_padded_header_naming_the_caller_is_still_the_callers_own_team(
    sm: sessionmaker[Session],
) -> None:
    """Servers differ on trimming header values; padding must not change the answer."""
    lead = add_user(sm, Role.teacher)
    resp = client(sm, lead).get(f"{BASE}/seats", headers={ACTING_TEACHER_HEADER: f" {lead} "})
    assert resp.status_code == 200


def test_an_assistant_without_the_header_reaches_only_their_own_empty_team(
    sm: sessionmaker[Session],
) -> None:
    lead, helper, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, lead, included_seats=3)
    seat = add_seat(sm, teacher_id=lead, student_id=student)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.co_teacher)
    c = client(sm, helper)
    assert c.delete(f"{BASE}/seats/{seat}").status_code == 404
    assert c.get(f"{BASE}/seats").json() == {"seats": []}
    assert c.get(f"{BASE}/capacity").json()["capacity"] == 0
    invite = c.post(f"{BASE}/assistants/invites", json={"role": "co_teacher"})
    assert invite.status_code == 201
    with sm() as session:
        # The invite is for the assistant's own team, never the lead's.
        assert set(session.scalars(select(Invite.team_teacher_id))) == {helper}
        seats = TeacherTeamService(session).list_seats(lead)
        assert [(s.id, s.status) for s in seats] == [(seat, TeacherMemberStatus.active)]


# ── invites and redemption ────────────────────────────────────────────────────


def test_invite_then_redeem_then_membership(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher, display_name="Ms Hoda")
    helper = add_user(sm, Role.teacher)
    invite = client(sm, lead).post(
        f"{BASE}/assistants/invites", json={"role": "marker", "expiresInDays": 3}
    )
    assert invite.status_code == 201
    code = invite.json()["code"]
    assert invite.json()["role"] == "marker"
    redeemed = client(sm, helper).post(f"{BASE}/assistants/redeem", json={"code": code})
    assert redeemed.status_code == 200
    assert redeemed.json()["teacherId"] == str(lead)
    assert redeemed.json()["teacherName"] == "Ms Hoda"
    assert redeemed.json()["effectivePermissions"] == ["mark", "regrade", "view_results"]
    memberships = client(sm, helper).get(f"{BASE}/memberships").json()["memberships"]
    assert [m["teacherId"] for m in memberships] == [str(lead)]
    assistants = client(sm, lead).get(f"{BASE}/assistants").json()["assistants"]
    assert [a["assistantId"] for a in assistants] == [str(helper)]


def test_invite_wire_fields_are_exactly_the_frontend_contract(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher)
    created = client(sm, lead).post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()
    assert set(created) == {"inviteId", "code", "role", "expiresAt", "createdAt"}
    uuid.UUID(created["inviteId"])


@pytest.mark.parametrize(
    ("body", "days"),
    [
        ({"role": "viewer"}, 7),
        ({"role": "viewer", "expiresInDays": 1}, 1),
        ({"role": "viewer", "expiresInDays": 30}, 30),
    ],
)
def test_the_router_computes_expiry_from_days_default_seven(
    sm: sessionmaker[Session], body: dict[str, object], days: int
) -> None:
    lead = add_user(sm, Role.teacher)
    before = datetime.now(UTC)
    resp = client(sm, lead).post(f"{BASE}/assistants/invites", json=body)
    after = datetime.now(UTC)
    assert resp.status_code == 201
    expires = datetime.fromisoformat(resp.json()["expiresAt"])
    assert before + timedelta(days=days) <= expires <= after + timedelta(days=days)


@pytest.mark.parametrize("days", [0, -1, 31, 365])
def test_expiry_outside_one_to_thirty_days_is_422_and_mints_nothing(
    sm: sessionmaker[Session], days: int
) -> None:
    lead = add_user(sm, Role.teacher)
    resp = client(sm, lead).post(
        f"{BASE}/assistants/invites", json={"role": "viewer", "expiresInDays": days}
    )
    assert resp.status_code == 422
    with sm() as session:
        assert session.scalar(select(func.count()).select_from(Invite)) == 0


def test_an_invite_for_an_unknown_role_is_422(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher)
    resp = client(sm, lead).post(f"{BASE}/assistants/invites", json={"role": "owner"})
    assert resp.status_code == 422


def test_the_live_invite_cap_is_a_409(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher)
    c = client(sm, lead)
    for _ in range(MAX_LIVE_ASSISTANT_INVITES):
        assert c.post(f"{BASE}/assistants/invites", json={"role": "viewer"}).status_code == 201
    over = c.post(f"{BASE}/assistants/invites", json={"role": "viewer"})
    assert over.status_code == 409
    assert over.json()["detail"]["code"] == "invite_limit"
    assert len(c.get(f"{BASE}/invites").json()["invites"]) == MAX_LIVE_ASSISTANT_INVITES
    # Revoking one frees a slot.
    first = c.get(f"{BASE}/invites").json()["invites"][0]["inviteId"]
    assert c.delete(f"{BASE}/invites/{first}").status_code == 204
    assert c.post(f"{BASE}/assistants/invites", json={"role": "viewer"}).status_code == 201


def test_list_and_revoke_invites(sm: sessionmaker[Session]) -> None:
    lead, intruder, helper = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    c = client(sm, lead)
    created = c.post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()
    listed = c.get(f"{BASE}/invites").json()["invites"]
    assert [(i["inviteId"], i["code"]) for i in listed] == [(created["inviteId"], created["code"])]
    invite_id = created["inviteId"]
    # IDOR: another teacher cannot see or revoke it, and learns nothing from the refusal.
    assert client(sm, intruder).get(f"{BASE}/invites").json() == {"invites": []}
    stranger = client(sm, intruder).delete(f"{BASE}/invites/{invite_id}")
    unknown = client(sm, intruder).delete(f"{BASE}/invites/{uuid.uuid4()}")
    assert stranger.status_code == 404  # 404, not 403: an id cannot be probed
    assert (stranger.status_code, stranger.json()) == (unknown.status_code, unknown.json())
    assert len(c.get(f"{BASE}/invites").json()["invites"]) == 1
    assert c.delete(f"{BASE}/invites/{invite_id}").status_code == 204
    assert c.get(f"{BASE}/invites").json() == {"invites": []}
    redeemed = client(sm, helper).post(f"{BASE}/assistants/redeem", json={"code": created["code"]})
    assert redeemed.status_code == 404  # a revoked code is gone


def test_a_redeemed_or_malformed_invite_cannot_be_revoked(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    c = client(sm, lead)
    created = c.post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()
    client(sm, helper).post(f"{BASE}/assistants/redeem", json={"code": created["code"]})
    assert c.delete(f"{BASE}/invites/{created['inviteId']}").status_code == 404
    assert c.delete(f"{BASE}/invites/not-a-uuid").status_code == 404
    with sm() as session:  # the spent invite row survives as the redemption record
        assert session.scalar(select(func.count()).select_from(Invite)) == 1


def test_an_assistant_cannot_revoke_the_leads_invites(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.co_teacher)
    created = client(sm, lead).post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()
    invite_path = f"{BASE}/invites/{created['inviteId']}"
    with_header = client(sm, helper).delete(invite_path, headers={ACTING_TEACHER_HEADER: str(lead)})
    assert with_header.status_code == 403
    without_header = client(sm, helper).delete(invite_path)
    assert without_header.status_code == 404
    assert len(client(sm, lead).get(f"{BASE}/invites").json()["invites"]) == 1


def test_redeem_requires_a_teacher_account(sm: sessionmaker[Session]) -> None:
    lead, student = add_user(sm, Role.teacher), add_user(sm)
    code = (
        client(sm, lead).post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()["code"]
    )
    resp = client(sm, student, Role.student).post(f"{BASE}/assistants/redeem", json={"code": code})
    assert resp.status_code == 403
    with sm() as session:
        assert session.scalar(select(func.count()).select_from(TeacherMember)) == 0


def test_a_teacher_cannot_redeem_their_own_invite(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher)
    c = client(sm, lead)
    code = c.post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()["code"]
    resp = c.post(f"{BASE}/assistants/redeem", json={"code": code})
    assert resp.status_code in (404, 409)
    with sm() as session:
        assert session.scalar(select(func.count()).select_from(TeacherMember)) == 0


def test_redeem_of_an_unknown_or_used_code(sm: sessionmaker[Session]) -> None:
    lead, h1, h2 = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    code = (
        client(sm, lead).post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()["code"]
    )
    assert client(sm, h1).post(f"{BASE}/assistants/redeem", json={"code": code}).status_code == 200
    used = client(sm, h2).post(f"{BASE}/assistants/redeem", json={"code": code})
    assert used.status_code == 409
    assert used.json()["detail"]["code"] == "invite_already_redeemed"
    unknown = client(sm, h2).post(f"{BASE}/assistants/redeem", json={"code": "NOSUCHCODE"})
    assert unknown.status_code == 404


@pytest.mark.parametrize("code", ["", "x" * 33])
def test_redeem_rejects_an_empty_or_oversized_code(sm: sessionmaker[Session], code: str) -> None:
    helper = add_user(sm, Role.teacher)
    assert (
        client(sm, helper).post(f"{BASE}/assistants/redeem", json={"code": code}).status_code == 422
    )


def test_redeem_is_rate_limited(sm: sessionmaker[Session]) -> None:
    helper = add_user(sm, Role.teacher)
    limiter = SlidingWindowLimiter(limit=2, window_seconds=600.0, clock=lambda: 0.0)
    c = client(sm, helper, limiter=limiter)
    responses = [c.post(f"{BASE}/assistants/redeem", json={"code": "NOSUCHCODE"}) for _ in range(3)]
    assert [r.status_code for r in responses] == [404, 404, 429]
    assert responses[2].headers["Retry-After"] == "600"
    assert responses[2].json()["detail"]["code"] == "rate_limited"


def test_the_real_redeem_limiter_is_ten_per_user_per_ten_minutes(sm: sessionmaker[Session]) -> None:
    """Pins the wired numbers: spec §7 says 10 attempts per 10 minutes, per user."""
    now = [1000.0]
    real: SlidingWindowLimiter = get_assistant_redeem_limiter.__wrapped__()
    # Same limit and window as the shipped limiter, on a clock the test controls.
    limiter = SlidingWindowLimiter(limit=10, window_seconds=600.0, clock=lambda: now[0])
    first, second = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    c1, c2 = client(sm, first, limiter=limiter), client(sm, second, limiter=limiter)
    statuses = [
        c1.post(f"{BASE}/assistants/redeem", json={"code": "NOSUCHCODE"}).status_code
        for _ in range(11)
    ]
    assert statuses == [404] * 10 + [429]
    # Another user has their own budget.
    assert c2.post(f"{BASE}/assistants/redeem", json={"code": "NOSUCHCODE"}).status_code == 404
    now[0] += 601.0  # the window rolls
    assert c1.post(f"{BASE}/assistants/redeem", json={"code": "NOSUCHCODE"}).status_code == 404
    # And the shipped limiter really is configured that way.
    assert [real.allow("probe") for _ in range(11)] == [True] * 10 + [False]
    assert 1 <= real.retry_after("probe") <= 600


def test_a_limited_caller_cannot_redeem_even_a_valid_code(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = (
        client(sm, lead).post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()["code"]
    )
    limiter = SlidingWindowLimiter(limit=1, window_seconds=600.0, clock=lambda: 0.0)
    c = client(sm, helper, limiter=limiter)
    assert c.post(f"{BASE}/assistants/redeem", json={"code": "NOSUCHCODE"}).status_code == 404
    assert c.post(f"{BASE}/assistants/redeem", json={"code": code}).status_code == 429
    with sm() as session:
        assert session.scalar(select(func.count()).select_from(TeacherMember)) == 0


def test_update_assistant_role_and_toggles(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    c = client(sm, lead)
    resp = c.patch(
        f"{BASE}/assistants/{member}",
        json={"role": "marker", "permissions": {"view_usage": True}},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "marker"
    assert resp.json()["permissions"] == {"view_usage": True}
    assert resp.json()["effectivePermissions"] == ["mark", "regrade", "view_results", "view_usage"]
    bad = c.patch(f"{BASE}/assistants/{member}", json={"permissions": {"billing": True}})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "invalid_permissions"
    assert "billing" not in bad.text
    # The refused toggle changed nothing.
    [row] = c.get(f"{BASE}/assistants").json()["assistants"]
    assert row["role"] == "marker"
    assert row["permissions"] == {"view_usage": True}


def test_assistant_wire_fields_are_exactly_the_frontend_contract(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper)
    [row] = client(sm, lead).get(f"{BASE}/assistants").json()["assistants"]
    assert set(row) == {
        "kind",
        "memberId",
        "assistantId",
        "assistantName",
        "role",
        "permissions",
        "effectivePermissions",
        "capUnits",
        "capPeriod",
        "capUsedUnits",
    }
    assert row["assistantName"] == "Assistant"  # no display name: never the email


def test_assistant_rows_carry_cap_use_and_no_email(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher, display_name="Sara")
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper)
    credits = add_grant(sm, owner_id=lead, kind=GrantKind.credit_pack, units=1000, at=NOW_REAL)
    add_entry(
        sm, grant_id=credits, member_id=member, kind=UsageEntryKind.settle, units=-30, at=NOW_REAL
    )
    [row] = client(sm, lead).get(f"{BASE}/assistants").json()["assistants"]
    assert (row["kind"], row["assistantName"], row["capUsedUnits"]) == ("assistant", "Sara", 30)
    assert "email" not in row


def test_remove_assistant(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper)
    c = client(sm, lead)
    assert c.delete(f"{BASE}/assistants/{member}").status_code == 204
    assert c.get(f"{BASE}/assistants").json() == {"assistants": []}
    with sm() as session:
        assert TeacherTeamService(session).assistant_membership(helper, lead) is None


def test_removed_assistant_has_no_membership(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, status=TeacherMemberStatus.removed)
    assert client(sm, helper).get(f"{BASE}/memberships").json() == {"memberships": []}


def test_membership_wire_fields_are_exactly_the_frontend_contract(
    sm: sessionmaker[Session],
) -> None:
    lead, helper = add_user(sm, Role.teacher, display_name="Ms Hoda"), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    [row] = client(sm, helper).get(f"{BASE}/memberships").json()["memberships"]
    assert row == {
        "memberId": str(member),
        "teacherId": str(lead),
        "teacherName": "Ms Hoda",
        "role": "viewer",
        "effectivePermissions": ["view_results", "view_usage"],
    }


@pytest.mark.parametrize(
    "role", [Role.student, Role.parent, Role.school_admin, Role.platform_admin]
)
def test_only_teachers_reach_the_team_router(sm: sessionmaker[Session], role: Role) -> None:
    user = add_user(sm, role)
    c = client(sm, user, role)
    seat, assistant, invite = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for method, path, body in _every_team_request(seat, assistant, invite):
        assert c.request(method, path, json=body).status_code == 403, (method, path)


# ── error mapping ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (NotATeacher("secret-id-123"), 403, "not_a_teacher"),
        (InvalidInviteExpiry("secret-id-123"), 422, "invalid_expiry"),
        (AssistantInviteNotFound("secret-id-123"), 404, "not_found"),
        (TeamMemberNotFound("secret-id-123"), 404, "not_found"),
        (AssistantInviteRedeemed("secret-id-123"), 409, "invite_already_redeemed"),
        (AssistantInviteLimitError("secret-id-123"), 409, "invite_limit"),
        (TeamStateError("secret-id-123"), 409, "conflict"),
        (InvalidPermissions("secret-id-123"), 422, "invalid_permissions"),
        (InvalidScope("secret-id-123"), 422, "invalid_scope"),
        (InvalidCap("secret-id-123"), 422, "invalid_cap"),
        (NoFreeSeat("secret-id-123"), 409, "no_free_seat"),
        (TeamError("secret-id-123"), 409, "conflict"),
    ],
)
def test_team_errors_map_to_fixed_bodies_that_never_echo_the_exception(
    exc: TeamError, status: int, code: str
) -> None:
    http = team_error_to_http(exc)
    detail = cast("dict[str, str]", http.detail)
    assert (http.status_code, detail["code"]) == (status, code)
    assert set(detail) == {"code", "message"}
    assert "secret-id-123" not in str(detail)


def test_not_a_teacher_is_checked_before_its_team_state_error_parent() -> None:
    """``NotATeacher`` subclasses ``TeamStateError`` (409); the 403 must win."""
    assert issubclass(NotATeacher, TeamStateError)
    assert team_error_to_http(NotATeacher("x")).status_code == 403
    assert team_error_to_http(TeamStateError("x")).status_code == 409
