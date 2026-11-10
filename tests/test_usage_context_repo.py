"""DB facts behind the payer chain (Task 5), against real Postgres.

Seats, the assistant row, debtors, the study-plan week, block facts, allowance sizes and
the server-side targets of a question and a quiz. Query counts are pinned too: the chain
context must not grow a query per seat.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import event

from lemely.core.metered_actions import MeteredAction, UsageTarget
from lemely.core.payer_chain import ChainContext, build_payer_chain
from lemely.core.usage_types import GrantScope, Payer
from lemely.db.class_repo import ClassService
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import (
    Role,
    SubscriptionStatus,
)
from lemely.db.models.quizzes import Quiz, QuizAssignment
from lemely.db.models.study_plan import StudyPlan
from lemely.db.models.team import CapPeriod, TeacherMember, TeacherMemberStatus
from lemely.db.models.usage import GrantKind, UsageDebt
from lemely.db.models.users import User
from lemely.db.usage_context_repo import (
    AssistantUnavailable,
    allowance_units,
    candidate_subjects,
    has_live_credit_grant,
    has_live_plan,
    load_block_facts,
    load_chain_context,
    quiz_assignment_target,
    self_review_target,
    study_plan_generated_this_week,
)
from tests.team_db import add_class, add_teacher_plan, enrol
from tests.usage_helpers import (
    NOW,
    assistant,
    attempt_with_points,
    give,
    put_in_school,
    quiz_with_assignment,
    seat,
    seat_grant,
    seed_catalogue,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker


def _debt(
    sm: sessionmaker[Session], owner: uuid.UUID, units: int, outstanding: int | None = None
) -> None:
    with sm.begin() as session:
        session.add(
            UsageDebt(
                owner_user_id=owner,
                job_id=None,
                units=units,
                outstanding=units if outstanding is None else outstanding,
            )
        )


def _plan(
    sm: sessionmaker[Session], student: uuid.UUID, *, subject: str, week: date, superseded: bool
) -> None:
    with sm.begin() as session:
        session.add(
            StudyPlan(
                user_id=student,
                subject_code=subject,
                week_start=week,
                weekly_hours=4.0,
                available=True,
                generated_at=NOW,
                superseded_at=NOW if superseded else None,
            )
        )


def _count_statements(sm: sessionmaker[Session], work: Callable[[Session], object]) -> int:
    seen: list[str] = []

    def record(*args: object) -> None:
        seen.append(str(args[2]))

    engine = sm.kw["bind"]
    event.listen(engine, "before_cursor_execute", record)
    try:
        with sm() as session:
            work(session)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(seen)


# -- load_chain_context -------------------------------------------------------------


def test_seats_load_active_and_leaving_oldest_first(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    t1, t2, t3 = (seed_user(sm, Role.teacher) for _ in range(3))
    newer = seat(
        sm,
        teacher=t1,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
        created_at=NOW - timedelta(days=1),
    )
    older = seat(
        sm,
        teacher=t2,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
        status=TeacherMemberStatus.leaving,
        created_at=NOW - timedelta(days=9),
    )
    seat(
        sm,
        teacher=t3,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
        status=TeacherMemberStatus.removed,
    )
    with sm() as session:
        ctx = load_chain_context(
            session,
            actor_user_id=student,
            action=MeteredAction.MARK_PAPER,
            subject_code="0580",
            assistant_member_id=None,
            now=NOW,
        )
    assert [s.member_id for s in ctx.seats] == [older, newer]
    assert ctx.seats[0].scope_actions == frozenset({"mark_paper"})
    assert ctx.seats[0].scope_subjects == frozenset({"0580"})
    assert ctx.seats[0].teacher_user_id == t2


def test_seat_view_carries_cap_and_period(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
        cap_units=250,
        cap_period=CapPeriod.total,
    )
    other = seed_user(sm, Role.teacher)
    seat(
        sm,
        teacher=other,
        student=student,
        subjects=["0625"],
        actions=[MeteredAction.MARK_PAPER],
        cap_units=None,
    )
    with sm() as session:
        ctx = load_chain_context(
            session,
            actor_user_id=student,
            action=MeteredAction.MARK_PAPER,
            subject_code="0580",
            assistant_member_id=None,
            now=NOW,
        )
    by_teacher = {s.teacher_user_id: s for s in ctx.seats}
    assert (by_teacher[teacher].cap_units, by_teacher[teacher].cap_period) == (250, "total")
    assert (by_teacher[other].cap_units, by_teacher[other].cap_period) == (None, "month")


def test_debtors_cover_the_actor_and_every_seat_teacher(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student, teacher, stranger = seed_user(sm), seed_user(sm, Role.teacher), seed_user(sm)
    seat(
        sm, teacher=teacher, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER]
    )
    _debt(sm, teacher, 5)
    _debt(sm, stranger, 5)
    with sm() as session:
        ctx = load_chain_context(
            session,
            actor_user_id=student,
            action=MeteredAction.MARK_PAPER,
            subject_code="0580",
            assistant_member_id=None,
            now=NOW,
        )
    assert ctx.debtors == frozenset({teacher})


def test_a_repaid_debt_does_not_make_a_debtor(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    _debt(sm, student, 5, outstanding=0)
    with sm() as session:
        ctx = load_chain_context(
            session,
            actor_user_id=student,
            action=MeteredAction.MARK_PAPER,
            subject_code=None,
            assistant_member_id=None,
            now=NOW,
        )
    assert ctx.debtors == frozenset()


def test_the_actors_own_debt_counts(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    _debt(sm, student, 5)
    with sm() as session:
        ctx = load_chain_context(
            session,
            actor_user_id=student,
            action=MeteredAction.MARK_PAPER,
            subject_code=None,
            assistant_member_id=None,
            now=NOW,
        )
    assert ctx.debtors == frozenset({student})


def test_assistant_row_loads_and_seats_are_ignored(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    member = assistant(sm, teacher=lead, member=helper, cap_units=300)
    # The helper also holds a seat under another teacher: it must not feed the chain.
    other = seed_user(sm, Role.teacher)
    seat(sm, teacher=other, student=helper, subjects=["0580"], actions=[MeteredAction.MARK_PAPER])
    _debt(sm, lead, 7)
    with sm() as session:
        ctx = load_chain_context(
            session,
            actor_user_id=helper,
            action=MeteredAction.REGRADE,
            subject_code=None,
            assistant_member_id=member,
            now=NOW,
        )
    assert ctx.assistant is not None
    assert (
        ctx.assistant.member_id,
        ctx.assistant.lead_teacher_user_id,
        ctx.assistant.cap_units,
    ) == (member, lead, 300)
    assert ctx.assistant.cap_period == "month"
    assert ctx.seats == ()
    assert ctx.debtors == frozenset({lead})


def _load_for_assistant(
    sm: sessionmaker[Session], actor: uuid.UUID, member: uuid.UUID, action: MeteredAction
) -> object:
    with sm() as session:
        return load_chain_context(
            session,
            actor_user_id=actor,
            action=action,
            subject_code=None,
            assistant_member_id=member,
            now=NOW,
        )


def test_a_foreign_assistant_member_id_is_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    lead, helper, intruder = (seed_user(sm, Role.teacher) for _ in range(3))
    member = assistant(sm, teacher=lead, member=helper)
    with pytest.raises(AssistantUnavailable) as caught:
        _load_for_assistant(sm, intruder, member, MeteredAction.REGRADE)
    assert caught.value.code == "team_permission_denied"


def test_a_removed_assistant_row_is_refused(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    member = assistant(sm, teacher=lead, member=helper)
    with sm.begin() as session:
        row = session.get(TeacherMember, member)
        assert row is not None
        row.status = TeacherMemberStatus.removed
    with pytest.raises(AssistantUnavailable) as caught:
        _load_for_assistant(sm, helper, member, MeteredAction.REGRADE)
    assert caught.value.code == "team_permission_denied"


def test_a_seat_row_id_is_refused_as_an_assistant(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(
        sm, teacher=teacher, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER]
    )
    with pytest.raises(AssistantUnavailable) as caught:
        _load_for_assistant(sm, student, member, MeteredAction.MARK_PAPER)
    assert caught.value.code == "team_permission_denied"


def test_an_unknown_assistant_member_id_is_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    helper = seed_user(sm, Role.teacher)
    with pytest.raises(AssistantUnavailable) as caught:
        _load_for_assistant(sm, helper, uuid.uuid4(), MeteredAction.REGRADE)
    assert caught.value.code == "team_permission_denied"


def test_a_lead_who_is_no_longer_a_teacher_is_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    member = assistant(sm, teacher=lead, member=helper)
    with sm.begin() as session:
        user = session.get(User, lead)
        assert user is not None
        user.role = Role.student
    with pytest.raises(AssistantUnavailable) as caught:
        _load_for_assistant(sm, helper, member, MeteredAction.REGRADE)
    assert caught.value.code == "team_permission_denied"


def test_a_lead_with_school_data_is_unavailable_not_denied(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    member = assistant(sm, teacher=lead, member=helper)
    put_in_school(sm, lead)
    with pytest.raises(AssistantUnavailable) as caught:
        _load_for_assistant(sm, helper, member, MeteredAction.REGRADE)
    assert caught.value.code == "team_lead_unavailable"


def test_a_school_lead_is_not_revealed_to_a_stranger(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Only the assistant who holds the row learns the lead is unavailable."""
    sm = migrated_sessionmaker
    lead, helper, stranger = (seed_user(sm, Role.teacher) for _ in range(3))
    member = assistant(sm, teacher=lead, member=helper)
    put_in_school(sm, lead)
    with pytest.raises(AssistantUnavailable) as caught:
        _load_for_assistant(sm, stranger, member, MeteredAction.REGRADE)
    assert caught.value.code == "team_permission_denied"


def test_the_assistants_own_balance_never_appears_in_the_chain(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    member = assistant(sm, teacher=lead, member=helper, cap_units=40)
    give(sm, helper, units=500)
    ctx = _load_for_assistant(sm, helper, member, MeteredAction.REGRADE)
    assert isinstance(ctx, ChainContext)
    chain = build_payer_chain(ctx)
    assert {p.owner_user_id for p in chain} == {lead}
    assert [p.scope for p in chain] == [GrantScope.ALLOWANCE, GrantScope.CREDITS]
    assert {p.teacher_member_id for p in chain} == {member}


def test_a_refused_assistant_never_falls_back_to_the_actors_own_chain(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The lead removes the assistant after the route guard: nothing is built, so the
    assistant's own allowance and credits cannot pay for the lead's work (R4)."""
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    member = assistant(sm, teacher=lead, member=helper)
    give(sm, helper, units=500)
    with sm.begin() as session:
        row = session.get(TeacherMember, member)
        assert row is not None
        row.status = TeacherMemberStatus.removed
    with sm() as session, pytest.raises(AssistantUnavailable):
        load_chain_context(
            session,
            actor_user_id=helper,
            action=MeteredAction.MARK_PAPER,
            subject_code=None,
            assistant_member_id=member,
            now=NOW,
        )


def test_study_plan_flag_is_read_only_for_the_study_plan_action(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    _plan(sm, student, subject="0580", week=date(2026, 11, 2), superseded=False)

    def flag(action: MeteredAction, subject: str | None) -> bool:
        with sm() as session:
            return load_chain_context(
                session,
                actor_user_id=student,
                action=action,
                subject_code=subject,
                assistant_member_id=None,
                now=NOW,
            ).study_plan_generated_this_week

    assert flag(MeteredAction.STUDY_PLAN, "0580") is True
    assert flag(MeteredAction.STUDY_PLAN, "0625") is False
    assert flag(MeteredAction.STUDY_PLAN, None) is False
    assert flag(MeteredAction.MARK_QUIZ, "0580") is False


def test_chain_context_feeds_the_pure_chain_end_to_end(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
        cap_units=100,
    )
    with sm() as session:
        ctx = load_chain_context(
            session,
            actor_user_id=student,
            action=MeteredAction.MARK_PAPER,
            subject_code="0580",
            assistant_member_id=None,
            now=NOW,
        )
    chain = build_payer_chain(ctx)
    assert [(p.owner_user_id, p.scope, p.teacher_member_id) for p in chain] == [
        (student, GrantScope.SEAT, member),
        (teacher, GrantScope.CREDITS, member),
        (student, GrantScope.ALLOWANCE, None),
        (student, GrantScope.CREDITS, None),
    ]
    assert chain[1].cap_units == 100
    assert chain[1].cap_window_start == datetime(2026, 11, 1, tzinfo=UTC)


def test_chain_context_query_count_does_not_grow_with_seats(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    solo, busy = seed_user(sm), seed_user(sm)
    seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=solo,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
    )
    for _ in range(6):
        seat(
            sm,
            teacher=seed_user(sm, Role.teacher),
            student=busy,
            subjects=["0580"],
            actions=[MeteredAction.MARK_PAPER],
        )

    def load(user: uuid.UUID) -> Callable[[Session], object]:
        def run(session: Session) -> object:
            return load_chain_context(
                session,
                actor_user_id=user,
                action=MeteredAction.STUDY_PLAN,
                subject_code="0580",
                assistant_member_id=None,
                now=NOW,
            )

        return run

    one, many = _count_statements(sm, load(solo)), _count_statements(sm, load(busy))
    assert one == many
    assert many <= 3  # seats, debtors, study-plan week


def test_assistant_context_query_count_is_small(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    member = assistant(sm, teacher=lead, member=helper)

    def run(session: Session) -> object:
        return load_chain_context(
            session,
            actor_user_id=helper,
            action=MeteredAction.REGRADE,
            subject_code=None,
            assistant_member_id=member,
            now=NOW,
        )

    assert _count_statements(sm, run) <= 2  # confirmation (one statement), debtors


def test_a_naive_now_is_refused(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    with sm() as session, pytest.raises(ValueError, match="timezone"):
        load_chain_context(
            session,
            actor_user_id=student,
            action=MeteredAction.MARK_PAPER,
            subject_code=None,
            assistant_member_id=None,
            now=datetime(2026, 11, 4, 10, 0),
        )


# -- study plan week ----------------------------------------------------------------


def test_study_plan_week_counts_superseded_plans(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    _plan(sm, student, subject="0580", week=date(2026, 11, 2), superseded=True)
    with sm() as session:
        assert study_plan_generated_this_week(
            session, user_id=student, subject_code="0580", now=NOW
        )
        assert not study_plan_generated_this_week(
            session, user_id=student, subject_code="0625", now=NOW
        )
        assert not study_plan_generated_this_week(
            session, user_id=student, subject_code="0580", now=NOW + timedelta(days=7)
        )


def test_study_plan_week_is_monday_to_sunday_in_utc(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    _plan(sm, student, subject="0580", week=date(2026, 11, 2), superseded=False)
    monday = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    sunday = datetime(2026, 11, 8, 23, 59, tzinfo=UTC)
    prior_sunday = datetime(2026, 11, 1, 23, 59, tzinfo=UTC)
    next_monday = datetime(2026, 11, 9, 0, 0, tzinfo=UTC)
    with sm() as session:

        def seen(at: datetime) -> bool:
            return study_plan_generated_this_week(
                session, user_id=student, subject_code="0580", now=at
            )

        assert seen(monday) and seen(sunday)
        assert not seen(prior_sunday) and not seen(next_monday)
        # 01:00 Monday at UTC+2 is still Sunday in UTC, so it belongs to the prior week.
        assert not seen(datetime(2026, 11, 2, 1, 0, tzinfo=timezone(timedelta(hours=2))))


def test_study_plan_week_is_per_user(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student, other = seed_user(sm), seed_user(sm)
    _plan(sm, student, subject="0580", week=date(2026, 11, 2), superseded=False)
    with sm() as session:
        assert not study_plan_generated_this_week(
            session, user_id=other, subject_code="0580", now=NOW
        )


# -- candidate_subjects -------------------------------------------------------------


def test_candidate_subjects_lists_seat_subjects_for_the_action(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    seat(
        sm,
        teacher=teacher,
        student=student,
        subjects=["0625", "0580"],
        actions=[MeteredAction.MARK_PAPER],
    )
    with sm() as session:
        assert candidate_subjects(
            session, actor_user_id=student, action=MeteredAction.MARK_PAPER
        ) == [None, "0580", "0625"]
        assert candidate_subjects(
            session, actor_user_id=student, action=MeteredAction.MARK_QUIZ
        ) == [None]
        assert candidate_subjects(session, actor_user_id=student, action=MeteredAction.REGRADE) == [
            None
        ]


def test_candidate_subjects_dedupes_across_seats_and_skips_removed(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=student,
        subjects=["0580", "0625"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=student,
        subjects=["0625"],
        actions=[MeteredAction.MARK_PAPER],
        status=TeacherMemberStatus.leaving,
    )
    seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=student,
        subjects=["0478"],
        actions=[MeteredAction.MARK_PAPER],
        status=TeacherMemberStatus.removed,
    )
    with sm() as session:
        assert candidate_subjects(
            session, actor_user_id=student, action=MeteredAction.MARK_PAPER
        ) == [None, "0580", "0625"]


def test_candidate_subjects_for_a_user_without_seats_is_just_none(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    with sm() as session:
        assert candidate_subjects(
            session, actor_user_id=teacher, action=MeteredAction.MARK_PAPER
        ) == [None]


# -- block facts --------------------------------------------------------------------


def test_block_facts_read_debt_scope_plan_and_credits(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    seat(
        sm, teacher=teacher, student=student, subjects=["0625"], actions=[MeteredAction.MARK_PAPER]
    )
    give(sm, student, units=5)
    _debt(sm, student, 3)
    with sm() as session:
        ctx = load_chain_context(
            session,
            actor_user_id=student,
            action=MeteredAction.SELF_REVIEW,
            subject_code="0625",
            assistant_member_id=None,
            now=NOW,
        )
        facts = load_block_facts(session, ctx, build_payer_chain(ctx), now=NOW)
        assert has_live_credit_grant(session, student, now=NOW)
    assert facts.last_resort_in_debt is True
    assert facts.seat_scope_miss is True
    assert facts.has_credit_grant is True
    assert facts.has_live_plan is False


def test_block_facts_for_an_assistant_read_the_lead(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    member = assistant(sm, teacher=lead, member=helper)
    add_teacher_plan(sm, lead, included_seats=1)
    give(sm, helper, units=50)  # the helper's own credits never fund team work
    _debt(sm, lead, 9)
    with sm() as session:
        ctx = load_chain_context(
            session,
            actor_user_id=helper,
            action=MeteredAction.REGRADE,
            subject_code=None,
            assistant_member_id=member,
            now=NOW,
        )
        facts = load_block_facts(session, ctx, build_payer_chain(ctx), now=NOW)
    assert facts.last_resort_in_debt is True
    assert facts.has_live_plan is True
    assert facts.has_credit_grant is False
    assert facts.seat_scope_miss is False


def test_block_facts_clean_account(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    with sm() as session:
        ctx = load_chain_context(
            session,
            actor_user_id=student,
            action=MeteredAction.MARK_PAPER,
            subject_code=None,
            assistant_member_id=None,
            now=NOW,
        )
        facts = load_block_facts(session, ctx, build_payer_chain(ctx), now=NOW)
    assert (facts.last_resort_in_debt, facts.seat_scope_miss) == (False, False)
    assert (facts.has_live_plan, facts.has_credit_grant) == (False, False)


@pytest.mark.parametrize(
    ("status", "live"),
    [
        (SubscriptionStatus.active, True),
        (SubscriptionStatus.past_due, True),
        (SubscriptionStatus.cancelled, False),
        (SubscriptionStatus.expired, False),
        (SubscriptionStatus.inactive, False),
        (SubscriptionStatus.pending_first_payment, False),
        (SubscriptionStatus.rejected, False),
    ],
)
def test_has_live_plan_by_subscription_status(
    migrated_sessionmaker: sessionmaker[Session], status: SubscriptionStatus, live: bool
) -> None:
    sm = migrated_sessionmaker
    owner = seed_user(sm, Role.teacher)
    add_teacher_plan(sm, owner, included_seats=1, status=status)
    with sm() as session:
        assert has_live_plan(session, owner) is live


def test_has_live_credit_grant_ignores_hidden_expired_and_future_grants(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    owner = seed_user(sm)
    give(
        sm,
        owner,
        units=400,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=datetime(2026, 12, 1, tzinfo=UTC),
    )
    give(sm, owner, units=10, expires_at=NOW - timedelta(minutes=1))
    with sm() as session:
        assert not has_live_credit_grant(session, owner, now=NOW)
    give(sm, owner, units=10, expires_at=NOW + timedelta(days=1))
    with sm() as session:
        assert has_live_credit_grant(session, owner, now=NOW)
        assert not has_live_credit_grant(session, uuid.uuid4(), now=NOW)
        # A grant that is not effective yet is not live.
        assert not has_live_credit_grant(session, owner, now=NOW - timedelta(days=30))


# -- allowance_units ----------------------------------------------------------------


def test_allowance_units_sums_live_period_and_seat_grants(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(
        sm, teacher=teacher, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER]
    )
    give(
        sm,
        student,
        units=400,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=datetime(2026, 12, 1, tzinfo=UTC),
    )
    seat_grant(sm, student=student, member_id=member, units=150)
    with sm() as session:
        own = allowance_units(session, Payer(student, GrantScope.ALLOWANCE), now=NOW)
        seated = allowance_units(
            session, Payer(student, GrantScope.SEAT, teacher_member_id=member), now=NOW
        )
        credits = allowance_units(session, Payer(student, GrantScope.CREDITS), now=NOW)
    assert (own, seated, credits) == (400, 150, None)


def test_allowance_units_skips_expired_and_other_seats(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    mine = seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=student,
        subjects=["0580"],
        actions=[MeteredAction.MARK_PAPER],
    )
    other = seat(
        sm,
        teacher=seed_user(sm, Role.teacher),
        student=student,
        subjects=["0625"],
        actions=[MeteredAction.MARK_PAPER],
    )
    seat_grant(sm, student=student, member_id=other, units=999)
    give(
        sm,
        student,
        units=100,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=NOW - timedelta(hours=1),
    )
    # A signup grant is credits-style: it is not "your plan".
    give(sm, student, units=200, kind=GrantKind.signup)
    with sm() as session:
        assert allowance_units(session, Payer(student, GrantScope.ALLOWANCE), now=NOW) is None
        assert (
            allowance_units(
                session, Payer(student, GrantScope.SEAT, teacher_member_id=mine), now=NOW
            )
            is None
        )


# -- targets ------------------------------------------------------------------------


def test_self_review_target_reads_subject_and_point_count(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    attempt_id, qr_id = attempt_with_points(sm, student, subject="0625", points=3)
    with sm() as session:
        target = self_review_target(
            session,
            student_id=str(student),
            attempt_id=str(attempt_id),
            question_result_id=str(qr_id),
        )
    assert target == UsageTarget(subject_code="0625", input_count=3)


def test_self_review_target_with_no_points_or_subject(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    attempt_id, qr_id = attempt_with_points(sm, student, subject=None, points=0)
    with sm() as session:
        target = self_review_target(
            session,
            student_id=str(student),
            attempt_id=str(attempt_id),
            question_result_id=str(qr_id),
        )
    assert target == UsageTarget(subject_code=None, input_count=0)


def test_self_review_target_refuses_other_peoples_attempts_and_mismatched_ids(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    owner, intruder = seed_user(sm), seed_user(sm)
    attempt_id, qr_id = attempt_with_points(sm, owner, subject="0625", points=2)
    other_attempt, other_qr = attempt_with_points(sm, owner, subject="0580", points=1)
    with sm() as session:

        def target(student: object, attempt: object, qr: object) -> UsageTarget | None:
            return self_review_target(
                session,
                student_id=str(student),
                attempt_id=str(attempt),
                question_result_id=str(qr),
            )

        assert target(intruder, attempt_id, qr_id) is None
        assert target(owner, attempt_id, other_qr) is None  # question of another attempt
        assert target(owner, other_attempt, qr_id) is None
        assert target(owner, uuid.uuid4(), qr_id) is None
        assert target(owner, attempt_id, uuid.uuid4()) is None
        assert target("not-a-uuid", attempt_id, qr_id) is None
        assert target(owner, "nope", qr_id) is None
        assert target(owner, attempt_id, "nope") is None


def test_self_review_target_ignores_a_soft_deleted_attempt(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    attempt_id, qr_id = attempt_with_points(sm, student, subject="0625", points=2)
    with sm() as session:
        found = self_review_target(
            session,
            student_id=str(student),
            attempt_id=str(attempt_id),
            question_result_id=str(qr_id),
        )
    assert found is not None
    with sm.begin() as session:
        session.execute(sa.update(Attempt).where(Attempt.id == attempt_id).values(deleted_at=NOW))
    with sm() as session:
        assert (
            self_review_target(
                session,
                student_id=str(student),
                attempt_id=str(attempt_id),
                question_result_id=str(qr_id),
            )
            is None
        )


def _target(
    sm: sessionmaker[Session], student: uuid.UUID | str, assignment_id: str
) -> UsageTarget | None:
    with sm() as session:
        return quiz_assignment_target(session, student_id=str(student), assignment_id=assignment_id)


def test_quiz_assignment_target_counts_included_questions_only(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    assigned = quiz_with_assignment(sm, subject="0580", included=4, removed=2)
    assert _target(sm, assigned.owner, assigned.assignment_id) == UsageTarget(
        subject_code="0580", input_count=4
    )


def test_quiz_assignment_target_reads_a_class_assignment_of_an_enrolled_student(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    assigned = quiz_with_assignment(sm, subject="0625", included=3, via_class=True)
    assert _target(sm, assigned.owner, assigned.assignment_id) == UsageTarget(
        subject_code="0625", input_count=3
    )


def test_quiz_assignment_target_refuses_a_direct_assignment_of_someone_else(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    assigned = quiz_with_assignment(sm, subject="0580", included=4)
    stranger = seed_user(sm)
    assert _target(sm, stranger, assigned.assignment_id) is None


def test_quiz_assignment_target_refuses_a_class_the_caller_is_not_enrolled_in(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    assigned = quiz_with_assignment(sm, subject="0580", included=4, via_class=True)
    stranger = seed_user(sm)
    assert _target(sm, stranger, assigned.assignment_id) is None


def test_a_foreign_and_an_unknown_assignment_are_indistinguishable(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    assigned = quiz_with_assignment(sm, subject="0580", included=4)
    stranger = seed_user(sm)
    assert _target(sm, stranger, assigned.assignment_id) == _target(sm, stranger, str(uuid.uuid4()))


def test_quiz_assignment_target_refuses_malformed_ids(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    assigned = quiz_with_assignment(sm, subject="0580", included=4)
    assert _target(sm, assigned.owner, "nope") is None
    assert _target(sm, "nope", assigned.assignment_id) is None


def test_quiz_assignment_target_of_an_empty_quiz_counts_zero(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    assigned = quiz_with_assignment(sm, subject="0625", included=0, removed=1)
    assert _target(sm, assigned.owner, assigned.assignment_id) == UsageTarget(
        subject_code="0625", input_count=0
    )


def test_quiz_target_visibility_matches_the_enrolment_seam(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The in-transaction enrolment subquery agrees with ``enrolled_class_ids``."""
    sm = migrated_sessionmaker
    teacher, student = seed_user(sm, Role.teacher), seed_user(sm)
    enrolled = [add_class(sm, teacher_id=teacher, subject_code="0580")[0] for _ in range(2)]
    other = add_class(sm, teacher_id=teacher, subject_code="0580")[0]
    for class_id in enrolled:
        enrol(sm, class_id, student)
    quiz_id = uuid.uuid4()
    assignments: dict[uuid.UUID, uuid.UUID] = {}
    with sm.begin() as session:
        session.add(Quiz(id=quiz_id, teacher_id=teacher, subject_code="0580", title="Recap"))
        session.flush()
        for class_id in (*enrolled, other):
            assignment = QuizAssignment(quiz_id=quiz_id, class_id=class_id, assigned_by=teacher)
            session.add(assignment)
            session.flush()
            assignments[class_id] = assignment.id
    seam = set(ClassService(sm).enrolled_class_ids(student))
    assert seam == set(enrolled)
    for class_id, assignment_id in assignments.items():
        visible = _target(sm, student, str(assignment_id)) is not None
        assert visible == (class_id in seam)
