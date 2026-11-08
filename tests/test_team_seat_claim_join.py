"""Joining a teacher's class claims or extends a seat; no free seat refuses the join (§4.4)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import InviteService
from lemely.db.models import ClassEnrollment, Invite, School
from lemely.db.models.enums import InviteRole, Role
from lemely.db.parent_repo import ParentLinkService
from lemely.db.teacher_team_repo import (
    AssistantInviteLimitError,
    AssistantInviteNotFound,
    AssistantInviteRedeemed,
    InvalidCap,
    InvalidPermissions,
    InvalidScope,
    NoFreeSeat,
    TeacherTeamService,
    TeamError,
    TeamMemberNotFound,
    TeamStateError,
)
from lemely.runtime.config import Settings, TeamSettings
from lemely.web import deps
from lemely.web.app import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_class_service, get_invite_service
from lemely.web.team_http import NO_FREE_SEAT_MESSAGE, team_error_to_http
from tests.team_db import (
    add_assistant,
    add_class,
    add_teacher_plan,
    add_user,
    emptied_after,
    team_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def _enrolled(sm: sessionmaker[Session], class_id: uuid.UUID, student: uuid.UUID) -> bool:
    with sm() as session:
        count = session.scalar(
            select(func.count())
            .select_from(ClassEnrollment)
            .where(ClassEnrollment.class_id == class_id, ClassEnrollment.student_id == student)
        )
    return bool(count)


def _seats(sm: sessionmaker[Session], student: uuid.UUID) -> list[uuid.UUID]:
    with sm() as session:
        return [m.teacher_user_id for m in TeacherTeamService(session).seats_for_student(student)]


# ── ClassService ──────────────────────────────────────────────────────────────


def test_enforced_join_claims_a_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(student, code)
    assert _enrolled(sm, class_id, student)
    assert _seats(sm, student) == [teacher]


def test_enforced_join_without_a_free_seat_is_refused_and_rolled_back(
    sm: sessionmaker[Session],
) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    service = ClassService(sm, enforce_teacher_seats=True)
    service.join_by_code_with_notice(s1, code)
    with pytest.raises(NoFreeSeat):
        service.join_by_code_with_notice(s2, code)
    assert not _enrolled(sm, class_id, s2)
    assert _seats(sm, s2) == []


def test_enforced_join_of_a_teacher_without_a_plan_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(NoFreeSeat):
        ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(student, code)
    assert not _enrolled(sm, class_id, student)


def test_soft_join_without_a_free_seat_enrols_without_a_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=False).join_by_code_with_notice(student, code)
    assert _enrolled(sm, class_id, student)
    assert _seats(sm, student) == []


def test_soft_join_with_a_free_seat_still_claims_it(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    _, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=False).join_by_code_with_notice(student, code)
    assert _seats(sm, student) == [teacher]


def test_rejoining_the_same_class_keeps_one_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    _, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    service = ClassService(sm, enforce_teacher_seats=True)
    service.join_by_code_with_notice(student, code)
    service.join_by_code_with_notice(student, code)
    assert _seats(sm, student) == [teacher]


def test_a_school_class_takes_no_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Seat-free School", seat_quota=10))
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580", school_id=school_id)
    ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(student, code)
    assert _enrolled(sm, class_id, student)
    assert _seats(sm, student) == []


def test_a_teacher_joining_takes_no_seat(sm: sessionmaker[Session]) -> None:
    teacher, other_teacher = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(other_teacher, code)
    assert _enrolled(sm, class_id, other_teacher)
    assert _seats(sm, other_teacher) == []


def test_seats_are_enforced_by_default_and_off_under_the_suite() -> None:
    assert TeamSettings().enforce_teacher_seats is True
    assert Settings().team.enforce_teacher_seats is False  # tests/conftest.py's switch


def test_the_app_built_from_default_settings_enforces_seats(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LEMELY_TEAM__ENFORCE_TEACHER_SEATS", raising=False)
    deps.reset_singletons()
    try:
        assert deps.get_settings().team.enforce_teacher_seats is True
        assert deps.get_class_service()._enforce_teacher_seats is True
        assert ClassService(sm)._enforce_teacher_seats is True
    finally:
        deps.reset_singletons()


def test_the_suite_switch_reaches_direct_constructions(sm: sessionmaker[Session]) -> None:
    assert ClassService(sm)._enforce_teacher_seats is False


# ── HTTP: both join entry points answer 409 no_free_seat ─────────────────────


def _client(sm: sessionmaker[Session], student: uuid.UUID) -> TestClient:
    app: FastAPI = create_app()
    classes = ClassService(sm, enforce_teacher_seats=True)
    app.dependency_overrides[get_class_service] = lambda: classes
    app.dependency_overrides[get_invite_service] = lambda: InviteService(
        sm, classes, ParentLinkService(sm)
    )
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(student), role=Role.student.value
    )
    return TestClient(app)


def _full_class(sm: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID, str]:
    teacher, holder = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(holder, code)
    return teacher, class_id, code


def test_student_join_route_answers_409_no_free_seat(sm: sessionmaker[Session]) -> None:
    _, class_id, code = _full_class(sm)
    student = add_user(sm)
    resp = _client(sm, student).post("/api/student/classes/join", json={"joinCode": code})
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "no_free_seat", "message": NO_FREE_SEAT_MESSAGE}
    assert not _enrolled(sm, class_id, student)


def test_invite_redeem_of_a_bare_join_code_answers_409(sm: sessionmaker[Session]) -> None:
    _, class_id, code = _full_class(sm)
    student = add_user(sm)
    resp = _client(sm, student).post(f"/api/invites/{code}/redeem")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "no_free_seat"
    assert not _enrolled(sm, class_id, student)


def test_class_invite_redeem_answers_409_and_stays_unredeemed(sm: sessionmaker[Session]) -> None:
    teacher, class_id, _ = _full_class(sm)
    invite_code = f"C{uuid.uuid4().hex[:9].upper()}"
    with sm.begin() as session:
        session.add(
            Invite(code=invite_code, role=InviteRole.student, created_by=teacher, class_id=class_id)
        )
    student = add_user(sm)
    resp = _client(sm, student).post(f"/api/invites/{invite_code}/redeem")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "no_free_seat"
    with sm() as session:
        invite = session.scalars(select(Invite).where(Invite.code == invite_code)).one()
    assert invite.redeemed_by is None
    assert not _enrolled(sm, class_id, student)


# ── TeamStateError: assistant rows, school classes, self-joins ───────────────


def test_an_assistant_student_joining_is_refused_when_enforced(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(TeamStateError):
        ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(helper, code)
    assert not _enrolled(sm, class_id, helper)


def test_an_assistant_student_joining_is_enrolled_without_a_seat_when_not_enforced(
    sm: sessionmaker[Session],
) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=False).join_by_code_with_notice(helper, code)
    assert _enrolled(sm, class_id, helper)
    assert _seats(sm, helper) == []


def test_a_student_account_joining_its_own_class_is_refused_when_enforced(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)  # a student-role account that owns a class: corrupt but reachable
    class_id, code = add_class(sm, teacher_id=owner, subject_code="0580")
    with pytest.raises(TeamStateError):
        ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(owner, code)
    assert not _enrolled(sm, class_id, owner)


def test_a_school_class_join_never_attempts_a_claim(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a school class join must not attempt a seat claim")

    monkeypatch.setattr(TeacherTeamService, "claim_seat_for_class_join", forbidden)
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="No-Claim School", seat_quota=10))
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580", school_id=school_id)
    ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(student, code)
    assert _enrolled(sm, class_id, student)


def test_a_teacher_join_never_attempts_a_claim(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a teacher join must not attempt a seat claim")

    monkeypatch.setattr(TeacherTeamService, "claim_seat_for_class_join", forbidden)
    teacher, other = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(other, code)
    assert _enrolled(sm, class_id, other)


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (NoFreeSeat("x"), 409, "no_free_seat"),
        (TeamMemberNotFound("x"), 404, "not_found"),
        (AssistantInviteNotFound("x"), 404, "not_found"),
        (InvalidScope("x"), 422, "invalid_scope"),
        (InvalidCap("x"), 422, "invalid_cap"),
        (InvalidPermissions("x"), 422, "invalid_permissions"),
        (AssistantInviteRedeemed("x"), 409, "invite_already_redeemed"),
        (AssistantInviteLimitError("x"), 409, "invite_limit"),
        (TeamStateError("secret-id-123"), 409, "conflict"),
        (TeamError("secret-id-123"), 409, "conflict"),
    ],
)
def test_team_errors_map_to_fixed_http_bodies(exc: TeamError, status: int, code: str) -> None:
    http = team_error_to_http(exc)
    assert http.status_code == status
    detail = cast("dict[str, str]", http.detail)  # the team mapping always builds a dict body
    assert detail["code"] == code
    assert "secret-id-123" not in str(detail)


def test_student_join_route_answers_409_conflict_for_a_team_state_error(
    sm: sessionmaker[Session],
) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    resp = _client(sm, helper).post("/api/student/classes/join", json={"joinCode": code})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "conflict"
    assert not _enrolled(sm, class_id, helper)


def test_invite_redeem_route_answers_409_conflict_for_a_team_state_error(
    sm: sessionmaker[Session],
) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    resp = _client(sm, helper).post(f"/api/invites/{code}/redeem")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "conflict"
    assert not _enrolled(sm, class_id, helper)
