"""Assistants: invites, redemption, roles, toggles, removal (spec §2.3, §4.4, §7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from lemely.core.team_permissions import TeamPermission, effective_permissions
from lemely.db.class_repo import ClassService
from lemely.db.invite_codes import INVITE_CODE_ALPHABET, INVITE_CODE_LENGTH, generate_invite_code
from lemely.db.invite_repo import InviteRoleMismatchError, InviteService
from lemely.db.models import Invite
from lemely.db.models.enums import InviteRole, Role
from lemely.db.models.team import (
    AssistantRole,
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from lemely.db.parent_repo import ParentLinkService
from lemely.db.teacher_team_repo import (
    MAX_LIVE_ASSISTANT_INVITES,
    AssistantInviteLimitError,
    AssistantInviteNotFound,
    AssistantInviteRedeemed,
    InvalidPermissions,
    NotATeacher,
    TeacherTeamService,
    TeamMemberNotFound,
    TeamStateError,
)
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.team_db import (
    NOW,
    add_assistant,
    add_seat,
    add_user,
    emptied_after,
    team_database,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def run[T](sm: sessionmaker[Session], fn: Callable[[TeacherTeamService], T]) -> T:
    with sm.begin() as session:
        return fn(TeacherTeamService(session))


FAR = NOW + timedelta(days=3650)
"""Expiry for invites a test redeems or previews: InviteService.preview reads the real
clock, so a near expiry would make these tests fail once the calendar passes it."""


def mint(sm: sessionmaker[Session], teacher: uuid.UUID, role: AssistantRole) -> str:
    return run(
        sm,
        lambda team: team.create_assistant_invite(teacher, role=role, expires_at=FAR).code,
    )


def redeem(sm: sessionmaker[Session], code: str, user: uuid.UUID) -> uuid.UUID:
    return run(sm, lambda team: team.redeem_assistant_invite(code=code, user_id=user, now=NOW).id)


def invite_row(sm: sessionmaker[Session], code: str) -> Invite:
    with sm() as session:
        return session.scalars(select(Invite).where(Invite.code == code)).one()


def member_rows(sm: sessionmaker[Session], teacher: uuid.UUID) -> list[TeacherMember]:
    with sm() as session:
        return list(
            session.scalars(select(TeacherMember).where(TeacherMember.teacher_user_id == teacher))
        )


def test_generated_codes_use_the_invite_alphabet() -> None:
    code = generate_invite_code()
    assert len(code) == INVITE_CODE_LENGTH
    assert set(code) <= set(INVITE_CODE_ALPHABET)


def test_invite_codes_keep_their_published_shape() -> None:
    assert INVITE_CODE_LENGTH == 10
    assert INVITE_CODE_ALPHABET == "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    assert len({generate_invite_code() for _ in range(50)}) == 50


def test_create_assistant_invite_is_single_use_and_expiring(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.marker)
    invite = invite_row(sm, code)
    assert invite.role is InviteRole.assistant
    assert invite.team_teacher_id == teacher
    assert invite.created_by == teacher
    assert invite.assistant_role is AssistantRole.marker
    assert invite.reusable is False
    assert invite.expires_at == FAR


@pytest.mark.parametrize("role", [Role.student, Role.parent, Role.school_admin])
def test_only_a_teacher_can_mint_assistant_invites(sm: sessionmaker[Session], role: Role) -> None:
    user = add_user(sm, role)
    with pytest.raises(NotATeacher):
        mint(sm, user, AssistantRole.viewer)
    with sm() as session:
        assert session.scalar(select(func.count()).select_from(Invite)) == 0


def test_minting_for_an_unknown_account_is_refused(sm: sessionmaker[Session]) -> None:
    with pytest.raises(NotATeacher):
        mint(sm, uuid.uuid4(), AssistantRole.viewer)


def test_naive_expiry_is_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    with pytest.raises(ValueError, match="timezone-aware"):
        run(
            sm,
            lambda team: team.create_assistant_invite(
                teacher, role=AssistantRole.viewer, expires_at=datetime(2030, 1, 1)
            ),
        )


def test_live_assistant_invites_are_capped(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    for _ in range(MAX_LIVE_ASSISTANT_INVITES):
        mint(sm, teacher, AssistantRole.viewer)
    with pytest.raises(AssistantInviteLimitError):
        mint(sm, teacher, AssistantRole.viewer)
    other = add_user(sm, Role.teacher)
    mint(sm, other, AssistantRole.viewer)  # the cap is per teacher


def test_expired_and_redeemed_invites_free_the_cap(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    stale = datetime.now(UTC) - timedelta(minutes=1)  # the cap reads the database clock
    for _ in range(MAX_LIVE_ASSISTANT_INVITES - 1):
        mint(sm, teacher, AssistantRole.viewer)
    run(
        sm,
        lambda team: team.create_assistant_invite(
            teacher, role=AssistantRole.viewer, expires_at=stale
        ),
    )
    redeem(sm, mint(sm, teacher, AssistantRole.viewer), helper)
    mint(sm, teacher, AssistantRole.viewer)  # 19 live + 1 expired + 1 redeemed: one slot left
    with pytest.raises(AssistantInviteLimitError):
        mint(sm, teacher, AssistantRole.viewer)
    with sm() as session:
        total = session.scalar(select(func.count()).select_from(Invite))
    assert total == MAX_LIVE_ASSISTANT_INVITES + 2  # the live ones, the expired, the redeemed


def test_concurrent_mints_cannot_pass_the_cap(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    for _ in range(MAX_LIVE_ASSISTANT_INVITES - 1):
        mint(sm, teacher, AssistantRole.viewer)

    def second_mint() -> object:
        with sm.begin() as session:
            return TeacherTeamService(session).create_assistant_invite(
                teacher, role=AssistantRole.viewer, expires_at=FAR
            )

    first = sm()
    first.begin()
    try:
        TeacherTeamService(first).create_assistant_invite(
            teacher, role=AssistantRole.viewer, expires_at=FAR
        )
        worker = _Paused(second_mint)
        _wait_until_a_backend_waits_on_a_lock(sm)
        first.commit()
    finally:
        first.close()
    worker.join()
    assert isinstance(worker.error, AssistantInviteLimitError)
    with sm() as session:
        assert session.scalar(select(func.count()).select_from(Invite)) == (
            MAX_LIVE_ASSISTANT_INVITES
        )


def test_redeem_creates_an_active_assistant(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.marker)
    member_id = redeem(sm, code, helper)
    member = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert member is not None
    assert member.id == member_id
    assert member.kind is TeacherMemberKind.assistant
    assert member.role_preset is AssistantRole.marker
    assert member.permissions == {}
    assert member.cap_units is None
    assert member.cap_period is CapPeriod.month
    invite = invite_row(sm, code)
    assert invite.redeemed_by == helper
    assert invite.redeemed_at == NOW


def test_redeem_is_idempotent_for_the_same_user(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.viewer)
    assert redeem(sm, code, helper) == redeem(sm, code, helper)
    assert len(member_rows(sm, teacher)) == 1


def test_a_replay_keeps_the_role_and_toggles_an_assistant_has_since_been_given(
    sm: sessionmaker[Session],
) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.viewer)
    member = redeem(sm, code, helper)
    run(
        sm,
        lambda team: team.update_assistant(
            member, role=AssistantRole.marker, permissions={"regrade": False}
        ),
    )
    assert redeem(sm, code, helper) == member
    row = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert row is not None
    assert row.role_preset is AssistantRole.marker
    assert row.permissions == {"regrade": False}


def test_a_spent_invite_cannot_bring_a_removed_assistant_back(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.co_teacher)
    member = redeem(sm, code, helper)
    run(sm, lambda team: team.remove_assistant(member))
    with pytest.raises(AssistantInviteRedeemed):
        redeem(sm, code, helper)
    assert run(sm, lambda team: team.assistant_membership(helper, teacher)) is None


def test_redeem_by_a_second_user_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, h1, h2 = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    code = mint(sm, teacher, AssistantRole.viewer)
    redeem(sm, code, h1)
    with pytest.raises(AssistantInviteRedeemed):
        redeem(sm, code, h2)
    assert [m.member_user_id for m in member_rows(sm, teacher)] == [h1]


def test_two_sessions_redeeming_one_code_consume_it_exactly_once(
    sm: sessionmaker[Session],
) -> None:
    teacher, h1, h2 = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    code = mint(sm, teacher, AssistantRole.marker)

    def second_redeem() -> object:
        with sm.begin() as session:
            return TeacherTeamService(session).redeem_assistant_invite(
                code=code, user_id=h2, now=NOW
            )

    first = sm()
    first.begin()
    try:
        TeacherTeamService(first).redeem_assistant_invite(code=code, user_id=h1, now=NOW)
        worker = _Paused(second_redeem)
        _wait_until_a_backend_waits_on_a_lock(sm)
        first.commit()
    finally:
        first.close()
    worker.join()
    assert isinstance(worker.error, AssistantInviteRedeemed)
    assert invite_row(sm, code).redeemed_by == h1
    assert [m.member_user_id for m in member_rows(sm, teacher)] == [h1]


def test_expired_or_unknown_or_foreign_codes_are_not_found(sm: sessionmaker[Session]) -> None:
    teacher, helper, child = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.student),
    )
    expired = run(
        sm,
        lambda team: (
            team.create_assistant_invite(
                teacher, role=AssistantRole.viewer, expires_at=NOW - timedelta(seconds=1)
            ).code
        ),
    )
    parent_code = (
        InviteService(sm, ClassService(sm), ParentLinkService(sm))
        .mint_parent_invite(child, reusable=False)
        .code
    )
    for code in (expired, "NOSUCHCODE", parent_code):
        with pytest.raises(AssistantInviteNotFound):
            redeem(sm, code, helper)


def test_naive_redeem_clock_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.viewer)
    with pytest.raises(ValueError, match="timezone-aware"):
        run(
            sm,
            lambda team: team.redeem_assistant_invite(
                code=code, user_id=helper, now=datetime(2026, 11, 14, 12, 0)
            ),
        )


def test_list_and_revoke_assistant_invites(sm: sessionmaker[Session]) -> None:
    teacher, other, helper = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    live = mint(sm, teacher, AssistantRole.viewer)
    redeem(sm, mint(sm, teacher, AssistantRole.viewer), helper)
    run(
        sm,
        lambda team: team.create_assistant_invite(
            teacher, role=AssistantRole.viewer, expires_at=NOW - timedelta(seconds=1)
        ),
    )
    invites = run(sm, lambda team: team.list_assistant_invites(teacher, now=NOW))
    assert [i.code for i in invites] == [live]  # redeemed and expired ones are not listed
    invite_id = invites[0].id
    with pytest.raises(AssistantInviteNotFound):
        run(sm, lambda team: team.revoke_assistant_invite(other, invite_id))
    run(sm, lambda team: team.revoke_assistant_invite(teacher, invite_id))
    assert run(sm, lambda team: team.list_assistant_invites(teacher, now=NOW)) == []
    with pytest.raises(AssistantInviteNotFound):
        redeem(sm, live, helper)


def test_a_redeemed_invite_cannot_be_revoked(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.viewer)
    redeem(sm, code, helper)
    invite_id = invite_row(sm, code).id
    with pytest.raises(AssistantInviteNotFound):
        run(sm, lambda team: team.revoke_assistant_invite(teacher, invite_id))
    assert run(sm, lambda team: team.assistant_membership(helper, teacher)) is not None


def test_revoking_an_unknown_invite_is_not_found(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    with pytest.raises(AssistantInviteNotFound):
        run(sm, lambda team: team.revoke_assistant_invite(teacher, uuid.uuid4()))


def test_a_teacher_cannot_assist_themselves(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.viewer)
    with pytest.raises(TeamStateError):
        redeem(sm, code, teacher)
    assert invite_row(sm, code).redeemed_by is None
    assert member_rows(sm, teacher) == []


@pytest.mark.parametrize("role", [Role.student, Role.parent, Role.school_admin])
def test_only_a_teacher_account_can_redeem(sm: sessionmaker[Session], role: Role) -> None:
    teacher, outsider = add_user(sm, Role.teacher), add_user(sm, role)
    code = mint(sm, teacher, AssistantRole.viewer)
    with pytest.raises(NotATeacher):
        redeem(sm, code, outsider)
    assert invite_row(sm, code).redeemed_by is None
    assert member_rows(sm, teacher) == []


def test_an_unknown_redeemer_is_not_a_teacher(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.viewer)
    with pytest.raises(NotATeacher):
        redeem(sm, code, uuid.uuid4())
    assert invite_row(sm, code).redeemed_by is None


def test_a_seat_holder_cannot_become_the_same_teachers_assistant(
    sm: sessionmaker[Session],
) -> None:
    teacher, other = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    seat = add_seat(sm, teacher_id=teacher, student_id=other)
    code = mint(sm, teacher, AssistantRole.viewer)
    with pytest.raises(TeamStateError):
        redeem(sm, code, other)
    assert invite_row(sm, code).redeemed_by is None
    [row] = member_rows(sm, teacher)
    assert (row.id, row.kind) == (seat, TeacherMemberKind.student_seat)


def test_a_removed_seat_row_is_never_converted_to_an_assistant(sm: sessionmaker[Session]) -> None:
    teacher, other = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_seat(sm, teacher_id=teacher, student_id=other, status=TeacherMemberStatus.removed)
    with pytest.raises(TeamStateError):
        redeem(sm, mint(sm, teacher, AssistantRole.viewer), other)
    [row] = member_rows(sm, teacher)
    assert row.kind is TeacherMemberKind.student_seat


def test_a_live_assistant_cannot_redeem_a_second_invite_from_the_same_teacher(
    sm: sessionmaker[Session],
) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    existing = add_assistant(
        sm,
        teacher_id=teacher,
        assistant_id=helper,
        role=AssistantRole.marker,
        permissions={"mark": False},
    )
    code = mint(sm, teacher, AssistantRole.co_teacher)
    with pytest.raises(TeamStateError):
        redeem(sm, code, helper)
    assert invite_row(sm, code).redeemed_by is None  # the invite is not burnt
    [row] = member_rows(sm, teacher)
    assert row.id == existing
    assert row.role_preset is AssistantRole.marker
    assert row.permissions == {"mark": False}


def test_redeem_after_removal_reactivates_with_the_new_role(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    old = add_assistant(
        sm,
        teacher_id=teacher,
        assistant_id=helper,
        role=AssistantRole.co_teacher,
        permissions={"mark": False},
        status=TeacherMemberStatus.removed,
    )
    assert redeem(sm, mint(sm, teacher, AssistantRole.viewer), helper) == old
    member = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert member is not None
    assert member.role_preset is AssistantRole.viewer
    assert member.permissions == {}
    assert len(member_rows(sm, teacher)) == 1  # UPDATE in place, never a second row


def test_reactivation_clears_a_stale_cap_and_leave_date(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    old = add_assistant(
        sm, teacher_id=teacher, assistant_id=helper, status=TeacherMemberStatus.removed
    )
    with sm.begin() as session:
        row = session.get(TeacherMember, old)
        assert row is not None
        row.cap_units = 5
        row.cap_period = CapPeriod.total
        row.leaves_at = NOW
    redeem(sm, mint(sm, teacher, AssistantRole.viewer), helper)
    [row] = member_rows(sm, teacher)
    assert (row.cap_units, row.cap_period, row.leaves_at) == (None, CapPeriod.month, None)
    assert row.status is TeacherMemberStatus.active


def test_one_user_can_assist_several_teachers(sm: sessionmaker[Session]) -> None:
    t1, t2, helper = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    redeem(sm, mint(sm, t1, AssistantRole.viewer), helper)
    redeem(sm, mint(sm, t2, AssistantRole.marker), helper)
    teams = run(sm, lambda team: team.memberships_for_assistant(helper))
    assert [m.teacher_user_id for m in teams] == [t1, t2]


def test_membership_reads_only_active_assistants(sm: sessionmaker[Session]) -> None:
    t1, t2, helper = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    first = add_assistant(sm, teacher_id=t1, assistant_id=helper)
    add_assistant(sm, teacher_id=t2, assistant_id=helper, status=TeacherMemberStatus.removed)
    assert run(sm, lambda team: team.assistant_membership(helper, t2)) is None
    assert run(sm, lambda team: [m.id for m in team.memberships_for_assistant(helper)]) == [first]
    assert run(sm, lambda team: [m.id for m in team.list_assistants(t1)]) == [first]
    assert run(sm, lambda team: team.list_assistants(t2)) == []


def test_membership_and_listings_never_return_seats(sm: sessionmaker[Session]) -> None:
    teacher, other = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_seat(sm, teacher_id=teacher, student_id=other)
    assert run(sm, lambda team: team.assistant_membership(other, teacher)) is None
    assert run(sm, lambda team: team.memberships_for_assistant(other)) == []
    assert run(sm, lambda team: team.list_assistants(teacher)) == []


def test_update_assistant_role_and_toggles(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=teacher, assistant_id=helper, role=AssistantRole.viewer)
    run(
        sm,
        lambda team: team.update_assistant(
            member, role=AssistantRole.marker, permissions={"view_usage": True}
        ),
    )
    row = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert row is not None
    assert row.role_preset is AssistantRole.marker
    assert row.permissions == {"view_usage": True}
    run(sm, lambda team: team.update_assistant(member, role=None, permissions=None))
    row = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert row is not None
    assert row.role_preset is AssistantRole.marker  # None leaves each field unchanged
    assert row.permissions == {"view_usage": True}


def test_an_empty_toggle_map_clears_the_overrides(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(
        sm, teacher_id=teacher, assistant_id=helper, permissions={"view_usage": True}
    )
    run(sm, lambda team: team.update_assistant(member, role=None, permissions={}))
    row = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert row is not None
    assert row.permissions == {}


def test_effective_permissions_are_the_preset_plus_the_stored_overrides(
    sm: sessionmaker[Session],
) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=teacher, assistant_id=helper, role=AssistantRole.viewer)
    run(
        sm,
        lambda team: team.update_assistant(
            member,
            role=AssistantRole.marker,
            permissions={"view_results": False, "generate_quiz": True},
        ),
    )
    row = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert row is not None
    assert effective_permissions(row.role_preset or "", row.permissions or {}) == {
        TeamPermission.MARK,
        TeamPermission.REGRADE,
        TeamPermission.GENERATE_QUIZ,
    }


@pytest.mark.parametrize(
    "toggles",
    [
        {"billing": True},
        {"seats": True},
        {"manage_seats": True},
        {"manage_assistants": True},
        {"plan": True},
        {"mark": "yes"},
        {"mark": 1},
        {"mark": None},
    ],
)
def test_update_assistant_refuses_toggles_that_are_not_team_permissions(
    sm: sessionmaker[Session], toggles: dict[str, object]
) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(
        sm, teacher_id=teacher, assistant_id=helper, permissions={"view_usage": True}
    )
    with pytest.raises(InvalidPermissions):
        run(sm, lambda team: team.update_assistant(member, role=None, permissions=toggles))
    row = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert row is not None
    assert row.permissions == {"view_usage": True}  # nothing was half-applied


def test_a_refused_toggle_does_not_apply_the_role_change(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=teacher, assistant_id=helper, role=AssistantRole.viewer)
    with pytest.raises(InvalidPermissions):
        run(
            sm,
            lambda team: team.update_assistant(
                member, role=AssistantRole.co_teacher, permissions={"billing": True}
            ),
        )
    row = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert row is not None
    assert row.role_preset is AssistantRole.viewer


def test_update_and_remove_refuse_seats(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    with pytest.raises(TeamStateError):
        run(
            sm,
            lambda team: team.update_assistant(seat, role=AssistantRole.viewer, permissions=None),
        )
    with pytest.raises(TeamStateError):
        run(sm, lambda team: team.remove_assistant(seat))
    [row] = member_rows(sm, teacher)
    assert row.status is TeacherMemberStatus.active


def test_update_and_remove_refuse_a_removed_assistant(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    gone = add_assistant(
        sm, teacher_id=teacher, assistant_id=helper, status=TeacherMemberStatus.removed
    )
    with pytest.raises(TeamStateError):
        run(
            sm,
            lambda team: team.update_assistant(gone, role=AssistantRole.viewer, permissions=None),
        )
    with pytest.raises(TeamStateError):
        run(sm, lambda team: team.remove_assistant(gone))


def test_update_and_remove_of_an_unknown_member_are_not_found(sm: sessionmaker[Session]) -> None:
    with pytest.raises(TeamMemberNotFound):
        run(
            sm,
            lambda team: team.update_assistant(
                uuid.uuid4(), role=AssistantRole.viewer, permissions=None
            ),
        )
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.remove_assistant(uuid.uuid4()))


def test_remove_assistant_is_immediate(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    run(sm, lambda team: team.remove_assistant(member))
    assert run(sm, lambda team: team.assistant_membership(helper, teacher)) is None
    assert run(sm, lambda team: team.memberships_for_assistant(helper)) == []
    assert run(sm, lambda team: team.list_assistants(teacher)) == []
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.owned_member(teacher, member, kind=TeacherMemberKind.assistant))
    [row] = member_rows(sm, teacher)
    assert row.status is TeacherMemberStatus.removed
    assert row.leaves_at is None  # no month-end period for an assistant


def test_display_names_names_assistants_without_emails(sm: sessionmaker[Session]) -> None:
    named = add_user(sm, Role.teacher, display_name="Mr Sami")
    unnamed = add_user(sm, Role.teacher)
    assert run(sm, lambda team: team.display_names([named, unnamed])) == {
        named: "Mr Sami",
        unnamed: None,
    }


# ── InviteService: preview and generic redeem ────────────────────────────────


def test_generic_preview_names_the_lead_teacher(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher, display_name="Ms Hoda")
    code = mint(sm, teacher, AssistantRole.marker)
    preview = InviteService(sm, ClassService(sm), ParentLinkService(sm)).preview(code)
    assert preview.role is InviteRole.assistant
    assert preview.teacher_name == "Ms Hoda"
    assert preview.class_name is None
    assert preview.school_name is None
    assert preview.child_name is None


def test_generic_redeem_refuses_an_assistant_invite(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.marker)
    service = InviteService(sm, ClassService(sm), ParentLinkService(sm))
    with pytest.raises(InviteRoleMismatchError):
        service.redeem(helper, code, caller_role=Role.teacher)
    assert invite_row(sm, code).redeemed_by is None
    assert run(sm, lambda team: team.assistant_membership(helper, teacher)) is None
