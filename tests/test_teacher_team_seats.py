"""TeacherTeamService seats: capacity, claim, scope, cap, removal, release (§2.2, §4.4, §5.9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction
from lemely.db.models import PlanTier, School, Subscription
from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.team import (
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from lemely.db.models.usage import GrantKind, UsageDebt, UsageGrant, UsageGrantBalance
from lemely.db.teacher_team_repo import (
    SEAT_ACTIONS_OFF_BY_DEFAULT,
    InvalidCap,
    InvalidScope,
    NoFreeSeat,
    TeacherTeamService,
    TeacherTeamStore,
    TeamMemberNotFound,
    TeamStateError,
    default_seat_actions,
    month_end,
)
from lemely.db.usage_ledger_repo import UsageLedger
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.team_db import (
    NOW,
    add_assistant,
    add_class,
    add_seat,
    add_subject,
    add_teacher_plan,
    add_user,
    emptied_after,
    enrol,
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


def _set_scope_of(
    member: uuid.UUID, subjects: list[str], actions: list[str], team: TeacherTeamService
) -> None:
    team.set_scope(member, subjects=subjects, actions=actions)


def add_manual_teacher_plan(
    sm: sessionmaker[Session], teacher_id: uuid.UUID, *, included_seats: int
) -> None:
    """Seed a manual or complimentary subscription: ``payer_user_id`` is NULL (index R25)."""
    tier_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            PlanTier(
                id=tier_id,
                code=f"manual_{tier_id.hex[:8]}",
                name="Manual",
                price_minor=0,
                interval=PlanInterval.monthly,
                audience=PlanAudience.teacher,
                allowance_units=0,
                included_seats=included_seats,
                seat_allowance_units=0,
                extra_seat_price_minor=0,
                is_active=True,
            )
        )
        session.flush()
        session.add(
            Subscription(
                user_id=teacher_id,
                payer_user_id=None,
                plan_tier_id=tier_id,
                status=SubscriptionStatus.active,
                extra_seats=0,
            )
        )


def join(sm: sessionmaker[Session], class_id: uuid.UUID, student: uuid.UUID) -> uuid.UUID:
    """Enrol, then claim, as the class join flow does; return the seat id."""
    enrol(sm, class_id, student)
    return run(
        sm,
        lambda team: (
            team.claim_seat_for_class_join(student_user_id=student, class_id=class_id, now=NOW).id
        ),
    )


# ── capacity ────────────────────────────────────────────────────────────────


def test_capacity_is_zero_without_a_live_plan(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 0


def test_capacity_is_included_plus_extra(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_teacher_plan(sm, teacher, included_seats=2, extra_seats=3)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 5


def test_past_due_plan_keeps_its_seats(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_teacher_plan(sm, teacher, included_seats=2, status=SubscriptionStatus.past_due)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 2


def test_expired_plan_has_no_seats(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_teacher_plan(sm, teacher, included_seats=2, status=SubscriptionStatus.expired)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 0


def test_a_student_audience_plan_gives_no_seats(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_teacher_plan(sm, teacher, included_seats=2, audience=PlanAudience.student)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 0


# ── claim ───────────────────────────────────────────────────────────────────


def test_claim_creates_a_seat_with_default_scope(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    join(sm, class_id, student)
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.kind is TeacherMemberKind.student_seat
    assert seat.teacher_user_id == teacher
    assert seat.scope_subjects == ["0580"]
    assert seat.scope_actions == default_seat_actions()
    assert "study_plan" not in (seat.scope_actions or [])
    assert seat.cap_units is None
    assert seat.cap_period is CapPeriod.month
    assert seat.status is TeacherMemberStatus.active


def test_a_second_class_of_the_same_teacher_uses_the_same_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    maths, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    physics, _ = add_class(sm, teacher_id=teacher, subject_code="0625")
    first = join(sm, maths, student)
    second = join(sm, physics, student)
    assert first == second
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.scope_subjects == ["0580", "0625"]
    assert run(sm, lambda team: team.seats_used(teacher)) == 1


def test_a_class_without_subject_adds_no_subject(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    plain, _ = add_class(sm, teacher_id=teacher)
    join(sm, plain, student)
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.scope_subjects == []


def test_no_free_seat_when_full(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    join(sm, class_id, s1)
    with pytest.raises(NoFreeSeat):
        join(sm, class_id, s2)
    assert run(sm, lambda team: team.seats_for_student(s2)) == []


def test_no_plan_means_no_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(NoFreeSeat):
        join(sm, class_id, student)


def test_leaving_seats_still_count(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_seat(
        sm,
        teacher_id=teacher,
        student_id=s1,
        status=TeacherMemberStatus.leaving,
        leaves_at=month_end(NOW),
    )
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(NoFreeSeat):
        join(sm, class_id, s2)


def test_rejoin_while_leaving_stays_leaving_and_adds_the_subject(
    sm: sessionmaker[Session],
) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        subjects=["0580"],
        status=TeacherMemberStatus.leaving,
        leaves_at=month_end(NOW),
    )
    physics, _ = add_class(sm, teacher_id=teacher, subject_code="0625")
    join(sm, physics, student)
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.status is TeacherMemberStatus.leaving
    assert seat.scope_subjects == ["0580", "0625"]


def test_rejoin_after_removal_reactivates_with_fresh_scope(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    old = add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        subjects=["9709"],
        actions=["study_plan"],
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
        cap_units=50,
    )
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    assert join(sm, class_id, student) == old
    with sm() as session:  # the unique (teacher, member) pair holds: the row was updated
        assert (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(TeacherMember)
                .where(TeacherMember.member_user_id == student)
            )
            == 1
        )
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.status is TeacherMemberStatus.active
    assert seat.leaves_at is None
    assert seat.scope_subjects == ["0580"]
    assert seat.scope_actions == default_seat_actions()
    assert seat.cap_units is None


def test_rejoin_after_removal_needs_a_free_seat(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_seat(sm, teacher_id=teacher, student_id=s1)
    add_seat(
        sm,
        teacher_id=teacher,
        student_id=s2,
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
    )
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(NoFreeSeat):
        join(sm, class_id, s2)


def test_an_existing_seat_survives_a_lapsed_plan(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_seat(sm, teacher_id=teacher, student_id=student, subjects=["0580"])
    physics, _ = add_class(sm, teacher_id=teacher, subject_code="0625")
    join(sm, physics, student)
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.scope_subjects == ["0580", "0625"]


def test_an_assistant_row_cannot_become_a_seat(sm: sessionmaker[Session]) -> None:
    teacher, other = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_assistant(sm, teacher_id=teacher, assistant_id=other)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(TeamStateError):
        join(sm, class_id, other)


def test_concurrent_claims_cannot_exceed_capacity(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    enrol(sm, class_id, s1)
    enrol(sm, class_id, s2)

    def second_claim() -> object:
        with sm.begin() as session:
            return TeacherTeamService(session).claim_seat_for_class_join(
                student_user_id=s2, class_id=class_id, now=NOW
            )

    first = sm()
    first.begin()
    try:
        TeacherTeamService(first).claim_seat_for_class_join(
            student_user_id=s1, class_id=class_id, now=NOW
        )
        worker = _Paused(second_claim)
        _wait_until_a_backend_waits_on_a_lock(sm)
        first.commit()
    finally:
        first.close()
    worker.join()
    assert isinstance(worker.error, NoFreeSeat)
    assert run(sm, lambda team: team.seats_used(teacher)) == 1


# ── listing ─────────────────────────────────────────────────────────────────


def test_seats_for_student_are_oldest_first_and_exclude_removed(
    sm: sessionmaker[Session],
) -> None:
    t1, t2, t3, student = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm),
    )
    first = add_seat(sm, teacher_id=t1, student_id=student)
    second = add_seat(
        sm,
        teacher_id=t2,
        student_id=student,
        status=TeacherMemberStatus.leaving,
        leaves_at=month_end(NOW),
    )
    add_seat(
        sm,
        teacher_id=t3,
        student_id=student,
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
    )
    seats = run(sm, lambda team: [m.id for m in team.seats_for_student(student)])
    assert seats == [first, second]


def test_list_seats_is_the_teachers_own_held_seats(sm: sessionmaker[Session]) -> None:
    teacher, other, s1, s2 = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm),
        add_user(sm),
    )
    mine = add_seat(sm, teacher_id=teacher, student_id=s1)
    add_seat(sm, teacher_id=other, student_id=s2)
    assert run(sm, lambda team: [m.id for m in team.list_seats(teacher)]) == [mine]


def test_owned_member_is_not_found_for_another_teacher(sm: sessionmaker[Session]) -> None:
    teacher, other, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.owned_member(other, seat, kind=None))
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.owned_member(teacher, seat, kind=TeacherMemberKind.assistant))
    assert run(sm, lambda team: team.owned_member(teacher, seat, kind=None).id) == seat


# ── scope and cap ───────────────────────────────────────────────────────────


def test_set_scope_dedupes_sorts_and_accepts_study_plan(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_subject(sm, "0580")
    add_subject(sm, "0625", "Physics")
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    run(
        sm,
        lambda team: team.set_scope(
            seat,
            subjects=["0625", "0580", "0625"],
            actions=["study_plan", "mark_paper", "study_plan"],
        ),
    )
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.scope_subjects == ["0580", "0625"]
    assert row.scope_actions == ["mark_paper", "study_plan"]


def test_set_scope_refuses_unknown_actions_and_subjects(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_subject(sm, "0580")
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    with pytest.raises(InvalidScope):
        run(sm, lambda team: team.set_scope(seat, subjects=["0580"], actions=["buy_seats"]))
    with pytest.raises(InvalidScope):  # a teacher-side action is never seat-paid (R12)
        run(sm, lambda team: team.set_scope(seat, subjects=["0580"], actions=["regrade"]))
    with pytest.raises(InvalidScope):
        run(sm, lambda team: team.set_scope(seat, subjects=["9999"], actions=["mark_paper"]))


def test_set_scope_refuses_assistants_and_removed_seats(sm: sessionmaker[Session]) -> None:
    teacher, helper, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    removed = add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
    )
    for member in (assistant, removed):
        with pytest.raises(TeamStateError):
            run(sm, partial(_set_scope_of, member, [], []))


def test_set_cap(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    run(sm, lambda team: team.set_cap(seat, cap_units=300, cap_period=CapPeriod.total))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert (row.cap_units, row.cap_period) == (300, CapPeriod.total)
    run(sm, lambda team: team.set_cap(seat, cap_units=None, cap_period=CapPeriod.month))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.cap_units is None
    with pytest.raises(InvalidCap):
        run(sm, lambda team: team.set_cap(seat, cap_units=-5, cap_period=CapPeriod.month))


def test_unknown_member_is_not_found(sm: sessionmaker[Session]) -> None:
    unknown = uuid.uuid4()
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.set_cap(unknown, cap_units=1, cap_period=CapPeriod.month))


# ── removal and release ─────────────────────────────────────────────────────


def test_month_end_is_the_first_instant_of_next_month() -> None:
    assert month_end(datetime(2026, 11, 14, 12, tzinfo=UTC)) == datetime(2026, 12, 1, tzinfo=UTC)
    assert month_end(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == datetime(2027, 1, 1, tzinfo=UTC)


def test_request_removal_sets_leaving_until_month_end(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    run(sm, lambda team: team.request_removal(seat, now=NOW))
    run(sm, lambda team: team.request_removal(seat, now=NOW + timedelta(days=30)))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.status is TeacherMemberStatus.leaving
    assert row.leaves_at == datetime(2026, 12, 1, tzinfo=UTC)  # the second call changed nothing


def test_request_removal_refuses_assistants(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    with pytest.raises(TeamStateError):
        run(sm, lambda team: team.request_removal(assistant, now=NOW))


def test_release_due_frees_only_due_seats(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2, s3 = add_user(sm, Role.teacher), add_user(sm), add_user(sm), add_user(sm)
    due = add_seat(
        sm,
        teacher_id=teacher,
        student_id=s1,
        status=TeacherMemberStatus.leaving,
        leaves_at=NOW - timedelta(seconds=1),
    )
    add_seat(
        sm,
        teacher_id=teacher,
        student_id=s2,
        status=TeacherMemberStatus.leaving,
        leaves_at=NOW + timedelta(days=1),
    )
    add_seat(sm, teacher_id=teacher, student_id=s3)
    assert run(sm, lambda team: team.release_due(now=NOW)) == 1
    assert run(sm, lambda team: team.release_due(now=NOW)) == 0
    assert run(sm, lambda team: team.seats_used(teacher)) == 2
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.owned_member(teacher, due, kind=None))


# ── defaults ────────────────────────────────────────────────────────────────


def test_default_seat_actions_are_the_seat_actions_minus_the_opt_in_ones() -> None:
    assert frozenset({MeteredAction.STUDY_PLAN}) == SEAT_ACTIONS_OFF_BY_DEFAULT
    assert default_seat_actions() == sorted(
        action.value for action in SEAT_ACTIONS if action is not MeteredAction.STUDY_PLAN
    )
    assert default_seat_actions() == ["mark_paper", "self_review"]


# ── capacity and claim: more edges ──────────────────────────────────────────


def test_a_full_teacher_still_extends_an_existing_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    maths, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    physics, _ = add_class(sm, teacher_id=teacher, subject_code="0625")
    join(sm, maths, student)
    join(sm, physics, student)  # the seat is already held: no second seat, no NoFreeSeat
    assert run(sm, lambda team: team.seats_used(teacher)) == 1


def test_capacity_counts_extra_seats_when_claiming(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2, s3 = add_user(sm, Role.teacher), add_user(sm), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1, extra_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    join(sm, class_id, s1)
    join(sm, class_id, s2)
    with pytest.raises(NoFreeSeat):
        join(sm, class_id, s3)
    assert run(sm, lambda team: team.seats_used(teacher)) == 2


def test_a_refused_claim_leaves_the_session_usable_and_writes_nothing(
    sm: sessionmaker[Session],
) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=0)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    enrol(sm, class_id, s1)
    with sm.begin() as session, pytest.raises(NoFreeSeat):
        TeacherTeamService(session).claim_seat_for_class_join(
            student_user_id=s1, class_id=class_id, now=NOW
        )
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(TeacherMember)) == 0
    assert s2  # the unused student is only here to keep the teacher's roster realistic


def test_claiming_for_an_unknown_class_is_a_state_error(sm: sessionmaker[Session]) -> None:
    student = add_user(sm)
    with pytest.raises(TeamStateError):
        run(
            sm,
            lambda team: team.claim_seat_for_class_join(
                student_user_id=student, class_id=uuid.uuid4(), now=NOW
            ),
        )


def test_a_teacher_cannot_claim_a_seat_in_their_own_class(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(TeamStateError):
        run(
            sm,
            lambda team: team.claim_seat_for_class_join(
                student_user_id=teacher, class_id=class_id, now=NOW
            ),
        )


def test_default_scope_collects_the_subjects_of_the_students_school_less_classes(
    sm: sessionmaker[Session],
) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    maths, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    physics, _ = add_class(sm, teacher_id=teacher, subject_code="0625")
    other_teacher = add_user(sm, Role.teacher)
    chemistry, _ = add_class(sm, teacher_id=other_teacher, subject_code="0620")
    enrol(sm, maths, student)
    enrol(sm, chemistry, student)  # another teacher's class never enters this scope
    enrol(sm, physics, student)
    seat = run(
        sm,
        lambda team: team.claim_seat_for_class_join(
            student_user_id=student, class_id=physics, now=NOW
        ),
    )
    assert seat.scope_subjects == ["0580", "0625"]


# ── lock order and the ledger (R13, R14) ────────────────────────────────────


def test_claim_waits_on_the_subscription_row_and_times_out_under_a_holder(
    sm: sessionmaker[Session],
) -> None:
    """Holder pattern: while another transaction holds the plan row, the claim waits for it."""
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    sub_id = add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    enrol(sm, class_id, student)

    holder = sm()
    holder.begin()
    try:
        holder.execute(
            sa.select(Subscription.id).where(Subscription.id == sub_id).with_for_update()
        )
        with pytest.raises(OperationalError, match="lock timeout"), sm.begin() as session:
            session.execute(sa.text("SET LOCAL lock_timeout = '300ms'"))
            TeacherTeamService(session).claim_seat_for_class_join(
                student_user_id=student, class_id=class_id, now=NOW
            )
    finally:
        holder.rollback()
        holder.close()
    assert run(sm, lambda team: team.seats_for_student(student)) == []
    join_after_release = run(
        sm,
        lambda team: (
            team.claim_seat_for_class_join(student_user_id=student, class_id=class_id, now=NOW).id
        ),
    )
    assert join_after_release is not None


def test_claim_holds_the_subscription_lock_before_it_waits_for_the_member_row(
    sm: sessionmaker[Session],
) -> None:
    """Lock order: plan row first, then the member row (a later ledger lock comes after both)."""
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    sub_id = add_teacher_plan(sm, teacher, included_seats=1)
    seat = add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        subjects=["0580"],
        status=TeacherMemberStatus.leaving,
        leaves_at=month_end(NOW),
    )
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0625")
    enrol(sm, class_id, student)

    def claim() -> object:
        with sm.begin() as session:
            return TeacherTeamService(session).claim_seat_for_class_join(
                student_user_id=student, class_id=class_id, now=NOW
            )

    holder = sm()
    holder.begin()
    try:
        holder.execute(
            sa.select(TeacherMember.id).where(TeacherMember.id == seat).with_for_update()
        )
        worker = _Paused(claim)
        _wait_until_a_backend_waits_on_a_lock(sm)
        # The claim is queued behind the member row, so it must already hold the plan row.
        probe = sm()
        probe.begin()
        try:
            with pytest.raises(OperationalError, match="could not obtain lock"):
                probe.execute(
                    sa.select(Subscription.id)
                    .where(Subscription.id == sub_id)
                    .with_for_update(nowait=True)
                )
        finally:
            probe.rollback()
            probe.close()
        holder.commit()
    finally:
        holder.close()
    worker.join()
    assert worker.error is None
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.status is TeacherMemberStatus.leaving
    assert row.scope_subjects == ["0580", "0625"]


def test_a_claim_issues_no_grant(sm: sessionmaker[Session]) -> None:
    """The seat allowance is Phase 05's hook; the claim itself never touches the ledger."""
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    join(sm, class_id, student)
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(UsageGrant)) == 0


def test_a_seat_allowance_grant_on_a_claimed_seat_never_repays_student_debt(
    sm: sessionmaker[Session],
) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    seat_id = join(sm, class_id, student)
    with sm.begin() as session:
        session.add(UsageDebt(owner_user_id=student, units=30, outstanding=30))
    with sm.begin() as session:
        grant = UsageLedger(session).issue_grant(
            owner_user_id=student,
            kind=GrantKind.seat_allowance,
            units=40,
            idempotency_key=f"seat:{seat_id}:2026-11",
            expires_at=None,
            visible=False,
            teacher_member_id=seat_id,
        )
        grant_id = grant.id
    with sm() as session:
        balance = session.get(UsageGrantBalance, grant_id)
        assert balance is not None
        assert (balance.remaining, balance.held) == (40, 0)
        debt = session.scalars(sa.select(UsageDebt).where(UsageDebt.owner_user_id == student)).one()
        assert debt.outstanding == 30


# ── scope and cap: more edges ───────────────────────────────────────────────


def test_set_scope_is_per_subject_and_replaces_the_whole_list(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_subject(sm, "0580")
    add_subject(sm, "0625", "Physics")
    seat = add_seat(sm, teacher_id=teacher, student_id=student, subjects=["0580", "0625"])
    run(sm, lambda team: team.set_scope(seat, subjects=["0625"], actions=["mark_paper"]))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.scope_subjects == ["0625"]
    run(sm, lambda team: team.set_scope(seat, subjects=[], actions=[]))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert (row.scope_subjects, row.scope_actions) == ([], [])


def test_a_refused_scope_changes_nothing(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_subject(sm, "0580")
    seat = add_seat(sm, teacher_id=teacher, student_id=student, subjects=["0580"])
    with pytest.raises(InvalidScope):
        run(sm, lambda team: team.set_scope(seat, subjects=["0580"], actions=["regrade"]))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert (row.scope_subjects, row.scope_actions) == (["0580"], ["mark_paper"])


def test_set_scope_accepts_every_seat_action_and_no_other(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    every = sorted(action.value for action in SEAT_ACTIONS)
    run(sm, lambda team: team.set_scope(seat, subjects=[], actions=every))
    for action in MeteredAction:
        if action in SEAT_ACTIONS:
            continue
        with pytest.raises(InvalidScope):
            run(sm, partial(_set_scope_of, seat, [], [action.value]))


def test_set_cap_on_a_leaving_seat_and_on_an_assistant(sm: sessionmaker[Session]) -> None:
    teacher, helper, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    leaving = add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        status=TeacherMemberStatus.leaving,
        leaves_at=month_end(NOW),
    )
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    run(sm, lambda team: team.set_cap(leaving, cap_units=0, cap_period=CapPeriod.month))
    run(sm, lambda team: team.set_cap(assistant, cap_units=500, cap_period=CapPeriod.total))
    with sm() as session:
        rows = {
            row.id: (row.cap_units, row.cap_period)
            for row in session.scalars(sa.select(TeacherMember))
        }
    assert rows[leaving] == (0, CapPeriod.month)
    assert rows[assistant] == (500, CapPeriod.total)


def test_set_cap_refuses_a_removed_member(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    removed = add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
    )
    with pytest.raises(TeamStateError):
        run(sm, lambda team: team.set_cap(removed, cap_units=5, cap_period=CapPeriod.month))


# ── removal and release: more edges ─────────────────────────────────────────


def test_removal_in_december_leaves_at_the_start_of_the_next_year(
    sm: sessionmaker[Session],
) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    run(sm, lambda team: team.request_removal(seat, now=datetime(2026, 12, 31, 23, 59, tzinfo=UTC)))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.leaves_at == datetime(2027, 1, 1, tzinfo=UTC)


def test_request_removal_refuses_a_removed_seat_and_an_unknown_member(
    sm: sessionmaker[Session],
) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    removed = add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
    )
    with pytest.raises(TeamStateError):
        run(sm, lambda team: team.request_removal(removed, now=NOW))
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.request_removal(uuid.uuid4(), now=NOW))


def test_a_leaving_seat_counts_until_released_and_then_a_new_student_fits(
    sm: sessionmaker[Session],
) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    seat = join(sm, class_id, s1)
    run(sm, lambda team: team.request_removal(seat, now=NOW))
    with pytest.raises(NoFreeSeat):
        join(sm, class_id, s2)
    assert run(sm, lambda team: team.release_due(now=month_end(NOW) - timedelta(seconds=1))) == 0
    assert run(sm, lambda team: team.release_due(now=month_end(NOW))) == 1
    run(
        sm,
        lambda team: team.claim_seat_for_class_join(student_user_id=s2, class_id=class_id, now=NOW),
    )
    assert run(sm, lambda team: team.seats_used(teacher)) == 1
    assert run(sm, lambda team: team.seats_for_student(s1)) == []


def test_release_due_leaves_assistants_and_active_seats_alone(sm: sessionmaker[Session]) -> None:
    teacher, helper, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    assert run(sm, lambda team: team.release_due(now=NOW + timedelta(days=400))) == 0
    with sm() as session:
        statuses = {m.id: m.status for m in session.scalars(sa.select(TeacherMember))}
    assert statuses == {assistant: TeacherMemberStatus.active, seat: TeacherMemberStatus.active}


# ── display names and the store ─────────────────────────────────────────────


def test_display_names_returns_names_not_emails(sm: sessionmaker[Session]) -> None:
    named = add_user(sm, display_name="Amina")
    unnamed = add_user(sm)
    assert run(sm, lambda team: team.display_names([named, unnamed, uuid.uuid4()])) == {
        named: "Amina",
        unnamed: None,
    }
    assert run(sm, lambda team: team.display_names([])) == {}


def test_store_commits_on_exit_and_rolls_back_on_error(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    store = TeacherTeamStore(sm)
    with pytest.raises(RuntimeError, match="boom"), store.transaction() as team:
        team.request_removal(seat, now=NOW)
        raise RuntimeError("boom")
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.status is TeacherMemberStatus.active
    with store.transaction() as team:
        team.request_removal(seat, now=NOW)
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.status is TeacherMemberStatus.leaving


def test_a_removed_assistant_is_refused_and_the_row_is_unchanged(
    sm: sessionmaker[Session],
) -> None:
    teacher, person = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    old = add_assistant(
        sm,
        teacher_id=teacher,
        assistant_id=person,
        permissions={"mark": True},
        status=TeacherMemberStatus.removed,
    )
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(TeamStateError):
        join(sm, class_id, person)
    with sm() as session:
        row = session.scalars(
            sa.select(TeacherMember).where(TeacherMember.member_user_id == person)
        ).one()
    assert row.id == old
    assert row.kind is TeacherMemberKind.assistant
    assert row.status is TeacherMemberStatus.removed
    assert row.permissions == {"mark": True}
    assert (row.scope_subjects, row.scope_actions) == (None, None)
    assert run(sm, lambda team: team.seats_used(teacher)) == 0


def test_a_school_class_never_claims_a_teacher_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Team Test School"))
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580", school_id=school_id)
    with pytest.raises(TeamStateError):
        join(sm, class_id, student)
    assert run(sm, lambda team: team.seats_used(teacher)) == 0


def test_the_paid_plan_beats_a_manual_one_for_capacity(sm: sessionmaker[Session]) -> None:
    """Index R25: a manual row (no payer) older than the paid row must not win."""
    teacher = add_user(sm, Role.teacher)
    add_manual_teacher_plan(sm, teacher, included_seats=1)
    add_teacher_plan(sm, teacher, included_seats=3)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 3
    with sm.begin() as session:  # the paid row is chosen under the lock too
        assert TeacherTeamService(session)._capacity(teacher, lock=True) == 3


def test_a_manual_plan_alone_still_gives_its_seats(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_manual_teacher_plan(sm, teacher, included_seats=2)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 2


def test_month_end_and_release_due_refuse_naive_datetimes(sm: sessionmaker[Session]) -> None:
    naive = datetime(2026, 11, 14, 12, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        month_end(naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        run(sm, lambda team: team.release_due(now=naive))
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    with pytest.raises(ValueError, match="timezone-aware"):
        run(sm, lambda team: team.request_removal(seat, now=naive))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.status is TeacherMemberStatus.active


def test_a_reactivated_seat_keeps_its_original_created_at(sm: sessionmaker[Session]) -> None:
    """A rejoin updates the row, so the seat stays as old as its first claim."""
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    old = add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
    )
    with sm() as session:
        before = session.get(TeacherMember, old)
        assert before is not None
        created = before.created_at
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    join(sm, class_id, student)
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.id == old
    assert seat.created_at == created
