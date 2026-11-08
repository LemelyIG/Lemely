"""teacher_members constraints and the invites extension, on a create_all database (§4.4)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from lemely.core.team_permissions import AssistantRole as CoreAssistantRole
from lemely.db.base import Base
from lemely.db.models import Invite
from lemely.db.models.enums import InviteRole, Role
from lemely.db.models.team import (
    AssistantRole,
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from tests.team_db import NOW, add_assistant, add_seat, add_user, emptied_after, team_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def _insert(sm: sessionmaker[Session], row: object) -> None:
    with sm.begin() as session:
        session.add(row)


def test_core_and_model_assistant_roles_agree_member_for_member() -> None:
    """``lemely.db.models`` cannot import ``lemely.core``, so each declares the enum.

    The core members are upper-case (``CO_TEACHER``), the model's lower-case; pair them
    by lower-cased name and require the same stored value, so neither side can gain,
    lose or rename a role without this test failing.
    """
    core = {member.name.lower(): member.value for member in CoreAssistantRole}
    model = {member.name: member.value for member in AssistantRole}
    assert core == model
    assert model == {"co_teacher": "co_teacher", "marker": "marker", "viewer": "viewer"}


def test_invite_role_has_assistant() -> None:
    assert InviteRole("assistant") is InviteRole.assistant


def test_usage_grant_teacher_member_fk_targets_teacher_members() -> None:
    column = Base.metadata.tables["usage_grants"].c.teacher_member_id
    assert {fk.target_fullname for fk in column.foreign_keys} == {"teacher_members.id"}


def test_a_valid_seat_and_assistant_insert(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    student = add_user(sm, Role.student)
    helper = add_user(sm, Role.teacher)
    add_seat(sm, teacher_id=teacher, student_id=student, subjects=["0580"])
    add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    with sm() as session:
        assert session.query(TeacherMember).count() == 2


def test_seat_without_scope_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    row = TeacherMember(
        teacher_user_id=teacher,
        member_user_id=student,
        kind=TeacherMemberKind.student_seat,
        cap_period=CapPeriod.month,
    )
    with pytest.raises(IntegrityError, match="ck_teacher_members_seat_fields"):
        _insert(sm, row)


def test_assistant_with_scope_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    row = TeacherMember(
        teacher_user_id=teacher,
        member_user_id=helper,
        kind=TeacherMemberKind.assistant,
        role_preset=AssistantRole.viewer,
        permissions={},
        scope_subjects=["0580"],
        cap_period=CapPeriod.month,
    )
    with pytest.raises(IntegrityError, match="ck_teacher_members_assistant_fields"):
        _insert(sm, row)


def test_assistant_without_role_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    row = TeacherMember(
        teacher_user_id=teacher,
        member_user_id=helper,
        kind=TeacherMemberKind.assistant,
        permissions={},
        cap_period=CapPeriod.month,
    )
    with pytest.raises(IntegrityError, match="ck_teacher_members_assistant_fields"):
        _insert(sm, row)


def test_self_membership_is_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    with pytest.raises(IntegrityError, match="ck_teacher_members_not_self"):
        add_assistant(sm, teacher_id=teacher, assistant_id=teacher)


def test_one_row_per_teacher_and_member(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_seat(sm, teacher_id=teacher, student_id=student)
    with pytest.raises(IntegrityError, match="uq_teacher_members_teacher_member"):
        add_seat(sm, teacher_id=teacher, student_id=student)


def test_leaving_needs_a_date_and_active_has_none(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    with pytest.raises(IntegrityError, match="ck_teacher_members_leaving_has_date"):
        add_seat(sm, teacher_id=teacher, student_id=s1, status=TeacherMemberStatus.leaving)
    with pytest.raises(IntegrityError, match="ck_teacher_members_active_has_no_date"):
        add_seat(sm, teacher_id=teacher, student_id=s2, leaves_at=NOW)


def test_negative_cap_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    with pytest.raises(IntegrityError, match="ck_teacher_members_cap_nonnegative"):
        add_seat(sm, teacher_id=teacher, student_id=student, cap_units=-1)


def test_assistant_invite_targets_only_a_team(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    _insert(
        sm,
        Invite(
            code=f"A{uuid.uuid4().hex[:9].upper()}",
            role=InviteRole.assistant,
            created_by=teacher,
            team_teacher_id=teacher,
            assistant_role=AssistantRole.marker,
            expires_at=NOW,
        ),
    )
    with sm() as session:
        stored = session.query(Invite).one()
        assert stored.role is InviteRole.assistant
        assert stored.team_teacher_id == teacher
        assert stored.assistant_role is AssistantRole.marker


def test_assistant_invite_without_team_is_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    row = Invite(
        code=f"A{uuid.uuid4().hex[:9].upper()}",
        role=InviteRole.assistant,
        created_by=teacher,
        child_id=teacher,
        assistant_role=AssistantRole.marker,
    )
    with pytest.raises(IntegrityError, match="ck_invites_assistant_shape"):
        _insert(sm, row)


def test_assistant_invite_without_role_is_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    row = Invite(
        code=f"A{uuid.uuid4().hex[:9].upper()}",
        role=InviteRole.assistant,
        created_by=teacher,
        team_teacher_id=teacher,
    )
    with pytest.raises(IntegrityError, match="ck_invites_assistant_shape"):
        _insert(sm, row)


def test_non_assistant_invite_with_team_is_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    row = Invite(
        code=f"S{uuid.uuid4().hex[:9].upper()}",
        role=InviteRole.student,
        created_by=teacher,
        team_teacher_id=teacher,
    )
    with pytest.raises(IntegrityError, match="ck_invites_assistant_shape"):
        _insert(sm, row)


def test_non_assistant_invite_with_assistant_role_is_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    row = Invite(
        code=f"P{uuid.uuid4().hex[:9].upper()}",
        role=InviteRole.parent,
        created_by=teacher,
        child_id=teacher,
        assistant_role=AssistantRole.viewer,
    )
    with pytest.raises(IntegrityError, match="ck_invites_assistant_shape"):
        _insert(sm, row)


def test_invite_with_no_target_is_still_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    row = Invite(
        code=f"N{uuid.uuid4().hex[:9].upper()}", role=InviteRole.student, created_by=teacher
    )
    with pytest.raises(IntegrityError, match="ck_invites_target"):
        _insert(sm, row)
