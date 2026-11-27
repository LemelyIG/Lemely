"""Seat allowances: one grant per active seat per calendar month while the plan lives (§5.9).

Covers the monthly job (``grant_monthly_seat_allowances``), the on-claim grant, the claim hook in
``TeacherTeamService.claim_seat_for_class_join`` and the failure isolation both promise: a ledger
failure never refuses a class join and never stalls the other seats of the monthly job.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.core.subscription_rules import calendar_month_bounds
from lemely.db import seat_allowance_repo
from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.team import (
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from lemely.db.models.usage import GrantKind, UsageGrant, UsageGrantBalance
from lemely.db.seat_allowance_repo import (
    SEAT_GRANT_BATCH,
    grant_monthly_seat_allowances,
    grant_seat_allowance_on_claim,
    seat_grant_key,
)
from lemely.db.teacher_team_repo import TeacherTeamService, month_end
from lemely.db.usage_ledger_repo import UsageLedger
from tests.subscription_fixtures import (
    grants_of,
    seed_debt,
    seed_seat,
    seed_subscription,
    seed_tier,
    throwaway_database,
)
from tests.team_db import add_assistant, add_class, add_user, emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

MONTH_START = datetime(2026, 12, 1, 0, 0, 30, tzinfo=UTC)  # the first tick of the month
JAN_1 = datetime(2027, 1, 1, tzinfo=UTC)
NOV_15 = datetime(2026, 11, 15, 15, 0, tzinfo=UTC)  # 30-day month; 15th..30th is 16 days left
NOV_30 = datetime(2026, 11, 30, 23, 0, tzinfo=UTC)  # the last day: one day's worth
UNITS = 300


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def _teacher(
    sm: sessionmaker[Session],
    *,
    status: SubscriptionStatus = SubscriptionStatus.active,
    interval: PlanInterval = PlanInterval.monthly,
    units: int = UNITS,
) -> uuid.UUID:
    teacher = add_user(sm, Role.teacher)
    tier = seed_tier(
        sm,
        audience=PlanAudience.teacher,
        interval=interval,
        included_seats=5,
        seat_allowance_units=units,
    )
    seed_subscription(sm, user_id=teacher, tier_id=tier, payer_id=teacher, status=status)
    return teacher


def _student_seat(
    sm: sessionmaker[Session],
    teacher: uuid.UUID,
    status: TeacherMemberStatus = TeacherMemberStatus.active,
) -> tuple[uuid.UUID, uuid.UUID]:
    student = add_user(sm, Role.student)
    return student, seed_seat(sm, teacher_id=teacher, student_id=student, status=status)


def _monthly(sm: sessionmaker[Session], now: datetime, **kwargs: Any) -> int:
    return grant_monthly_seat_allowances(sm, now=now, **kwargs)


def _on_claim(sm: sessionmaker[Session], seat: uuid.UUID, now: datetime) -> UsageGrant | None:
    with sm.begin() as session:
        return grant_seat_allowance_on_claim(session, seat, now=now)


def _claim(
    sm: sessionmaker[Session], class_id: uuid.UUID, student: uuid.UUID, now: datetime
) -> TeacherMember:
    with sm.begin() as session:
        return TeacherTeamService(session).claim_seat_for_class_join(
            student_user_id=student, class_id=class_id, now=now
        )


def _fail_with_a_database_error(
    monkeypatch: pytest.MonkeyPatch, bad_owners: set[uuid.UUID]
) -> None:
    """Make ``issue_grant`` fail for ``bad_owners`` with a real SQL error.

    A SQL error aborts the surrounding transaction, which is what a ledger fault does in
    production: only per-seat transactions (and the claim's savepoint) contain it.
    """
    real = UsageLedger.issue_grant

    def failing(self: UsageLedger, **kwargs: Any) -> UsageGrant:
        if kwargs["owner_user_id"] in bad_owners:
            self._session.execute(sa.text("SELECT 1 / 0"))
        return real(self, **kwargs)

    monkeypatch.setattr(UsageLedger, "issue_grant", failing)


# ── the monthly job ─────────────────────────────────────────────────────────


def test_month_start_grants_each_active_seat_in_full(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm)
    a, seat_a = _student_seat(sm, teacher)
    _student_seat(sm, teacher)
    c, _ = _student_seat(sm, teacher, TeacherMemberStatus.leaving)
    d, _ = _student_seat(sm, teacher, TeacherMemberStatus.removed)

    assert _monthly(sm, MONTH_START) == 2

    [grant] = grants_of(sm, a)
    assert grant.kind is GrantKind.seat_allowance
    assert (grant.units, grant.visible, grant.teacher_member_id) == (UNITS, False, seat_a)
    assert grant.expires_at == JAN_1
    assert grant.effective_at == MONTH_START
    assert grant.idempotency_key == seat_grant_key(seat_a, datetime(2026, 12, 1, tzinfo=UTC))
    assert grant.idempotency_key == f"seat:{seat_a}:2026-12"


def test_leaving_and_removed_seats_get_nothing(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm)
    leaving, _ = _student_seat(sm, teacher, TeacherMemberStatus.leaving)
    removed, _ = _student_seat(sm, teacher, TeacherMemberStatus.removed)
    assert _monthly(sm, MONTH_START) == 0
    assert grants_of(sm, leaving) == [] and grants_of(sm, removed) == []


def test_a_second_run_grants_nothing_new(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm)
    student, _ = _student_seat(sm, teacher)
    assert _monthly(sm, MONTH_START) == 1
    assert _monthly(sm, MONTH_START) == 0
    assert _monthly(sm, datetime(2026, 12, 20, tzinfo=UTC)) == 0
    assert len(grants_of(sm, student)) == 1


def test_the_next_month_grants_again(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm)
    student, _ = _student_seat(sm, teacher)
    assert _monthly(sm, MONTH_START) == 1
    assert _monthly(sm, JAN_1.replace(second=30)) == 1
    assert [g.expires_at for g in grants_of(sm, student)] == [
        JAN_1,
        datetime(2027, 2, 1, tzinfo=UTC),
    ]


def test_yearly_and_past_due_plans_grant_monthly(sm: sessionmaker[Session]) -> None:
    yearly = _teacher(sm, interval=PlanInterval.yearly)
    grace = _teacher(sm, status=SubscriptionStatus.past_due)
    for teacher in (yearly, grace):
        _student_seat(sm, teacher)
    assert _monthly(sm, MONTH_START) == 2


@pytest.mark.parametrize(
    "status",
    [
        SubscriptionStatus.expired,
        SubscriptionStatus.cancelled,
        SubscriptionStatus.inactive,
        SubscriptionStatus.pending_first_payment,
    ],
)
def test_a_plan_that_is_not_live_grants_nothing(
    sm: sessionmaker[Session], status: SubscriptionStatus
) -> None:
    teacher = _teacher(sm, status=status)
    student, seat = _student_seat(sm, teacher)
    assert _monthly(sm, MONTH_START) == 0
    assert _on_claim(sm, seat, MONTH_START) is None
    assert grants_of(sm, student) == []


def test_a_tier_without_a_seat_allowance_grants_nothing(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm, units=0)
    student, seat = _student_seat(sm, teacher)
    assert _monthly(sm, MONTH_START) == 0
    assert _on_claim(sm, seat, MONTH_START) is None
    assert grants_of(sm, student) == []


def test_the_calendar_month_matches_the_team_modules_month_end() -> None:
    for now in (datetime(2026, 11, 14, 12, tzinfo=UTC), datetime(2026, 12, 31, 23, 59, tzinfo=UTC)):
        assert calendar_month_bounds(now)[1] == month_end(now)
    assert calendar_month_bounds(datetime(2026, 12, 31, 23, 59, tzinfo=UTC))[1] == JAN_1


# ── proration and dedupe on a claim ─────────────────────────────────────────


def test_a_mid_month_claim_is_prorated_to_the_days_left(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm)
    student, seat = _student_seat(sm, teacher)
    grant = _on_claim(sm, seat, NOV_15)
    # November has 30 days; the 15th to the 30th inclusive is 16 days left.
    assert grant is not None and grant.units == math.ceil(UNITS * 16 / 30) == 160
    assert grant.expires_at == datetime(2026, 12, 1, tzinfo=UTC)
    assert grant.effective_at == NOV_15
    again = _on_claim(sm, seat, NOV_15)
    assert again is not None and again.id == grant.id
    assert len(grants_of(sm, student)) == 1


def test_a_claim_on_the_last_day_grants_one_days_worth(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm)
    _, seat = _student_seat(sm, teacher)
    grant = _on_claim(sm, seat, NOV_30)
    assert grant is not None and grant.units == math.ceil(UNITS / 30) == 10


def test_a_later_visit_in_the_month_returns_the_stored_grant_untouched(
    sm: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A re-join later in the month finds the first grant (and its larger amount) as it was.

    The ledger's "grant replay differs" warning goes through stdlib logging, so ``caplog`` sees
    it (structlog's ``capture_logs`` does not); the early return never reaches ``issue_grant``.
    """
    teacher = _teacher(sm)
    student, seat = _student_seat(sm, teacher)
    first = _on_claim(sm, seat, NOV_15)
    calls: list[object] = []
    real = UsageLedger.issue_grant

    def spy(self: UsageLedger, **kwargs: Any) -> UsageGrant:
        calls.append(kwargs["idempotency_key"])
        return real(self, **kwargs)

    monkeypatch.setattr(UsageLedger, "issue_grant", spy)
    with caplog.at_level(logging.WARNING):
        later = _on_claim(sm, seat, NOV_30)
    assert first is not None and later is not None and later.id == first.id
    assert later.units == 160
    assert calls == []
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert len(grants_of(sm, student)) == 1


def test_removal_then_reclaim_in_the_same_month_grants_nothing_new(
    sm: sessionmaker[Session],
) -> None:
    teacher = _teacher(sm)
    student = add_user(sm, Role.student)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code=None)
    seat = _claim(sm, class_id, student, NOV_15).id
    [first] = grants_of(sm, student)
    with sm.begin() as session:  # the seat is released within the month
        session.execute(
            sa.update(TeacherMember)
            .where(TeacherMember.id == seat)
            .values(status=TeacherMemberStatus.removed)
        )
    assert _claim(sm, class_id, student, NOV_30).id == seat
    [only] = grants_of(sm, student)
    assert only.id == first.id and only.units == 160


def test_only_an_active_student_seat_is_granted(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm)
    assistant = add_user(sm, Role.student)
    assistant_row = add_assistant(sm, teacher_id=teacher, assistant_id=assistant)
    assert _on_claim(sm, assistant_row, MONTH_START) is None
    assert _on_claim(sm, uuid.uuid4(), MONTH_START) is None
    assert grants_of(sm, assistant) == []


# ── R25: which plan counts ──────────────────────────────────────────────────


def test_a_paid_plan_beats_a_manual_one_for_the_seat_allowance(sm: sessionmaker[Session]) -> None:
    """Index R25: the manual row is older, yet the paid row's tier decides the allowance."""
    teacher = add_user(sm, Role.teacher)
    manual_tier = seed_tier(
        sm, audience=PlanAudience.teacher, included_seats=5, seat_allowance_units=50
    )
    paid_tier = seed_tier(
        sm, audience=PlanAudience.teacher, included_seats=5, seat_allowance_units=700
    )
    seed_subscription(  # the manual row goes in first and is older
        sm,
        user_id=teacher,
        tier_id=manual_tier,
        payer_id=None,
        is_manually_activated=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    seed_subscription(
        sm,
        user_id=teacher,
        tier_id=paid_tier,
        payer_id=teacher,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    student, seat = _student_seat(sm, teacher)
    grant = _on_claim(sm, seat, MONTH_START)
    assert grant is not None and grant.units == 700
    other, other_seat = _student_seat(sm, teacher)
    assert _monthly(sm, MONTH_START) == 1
    [other_grant] = grants_of(sm, other)
    assert other_grant.teacher_member_id == other_seat and other_grant.units == 700
    assert [g.units for g in grants_of(sm, student)] == [700]


def test_a_manual_plan_without_a_seat_allowance_never_stalls_the_batch(
    sm: sessionmaker[Session],
) -> None:
    """The paid tier grants nothing, so its seats are not candidates and cannot fill the batch."""
    teacher = add_user(sm, Role.teacher)
    paid_tier = seed_tier(
        sm, audience=PlanAudience.teacher, included_seats=5, seat_allowance_units=0
    )
    manual_tier = seed_tier(
        sm, audience=PlanAudience.teacher, included_seats=5, seat_allowance_units=500
    )
    seed_subscription(sm, user_id=teacher, tier_id=paid_tier, payer_id=teacher)
    seed_subscription(
        sm, user_id=teacher, tier_id=manual_tier, payer_id=None, is_manually_activated=True
    )
    _student_seat(sm, teacher)
    granting = _teacher(sm)
    student, _ = _student_seat(sm, granting)
    assert _monthly(sm, MONTH_START, limit=1) == 1
    assert [g.units for g in grants_of(sm, student)] == [UNITS]


# ── R13: debt ───────────────────────────────────────────────────────────────


def test_seat_grant_never_repays_the_students_own_debt(sm: sessionmaker[Session]) -> None:
    """Index R13: teacher-funded seat units never pay the student's own debt."""
    teacher = _teacher(sm)
    student, _ = _student_seat(sm, teacher)
    seed_debt(sm, student, 50)
    assert _monthly(sm, MONTH_START) == 1
    [grant] = grants_of(sm, student)
    with sm() as session:
        balance = session.get(UsageGrantBalance, grant.id)
        assert balance is not None and balance.remaining == UNITS
        assert UsageLedger(session).has_debt(student)


# ── failure isolation ───────────────────────────────────────────────────────


def test_a_failing_seat_is_alerted_and_the_others_are_granted(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher = _teacher(sm)
    first, first_seat = _student_seat(sm, teacher)
    broken, broken_seat = _student_seat(sm, teacher)
    last, last_seat = _student_seat(sm, teacher)
    _fail_with_a_database_error(monkeypatch, {broken})

    with capture_logs() as logs:
        assert _monthly(sm, MONTH_START) == 2

    assert [len(grants_of(sm, s)) for s in (first, broken, last)] == [1, 0, 1]
    (alert,) = [e for e in logs if e["event"] == "seat_allowance_grant_failed"]
    assert (alert["log_level"], alert["alert"]) == ("error", True)
    assert alert["teacher_member_id"] == str(broken_seat)
    assert first_seat != last_seat
    monkeypatch.undo()  # the next tick repairs the one that failed
    assert _monthly(sm, MONTH_START) == 1
    assert len(grants_of(sm, broken)) == 1


def test_the_batch_limit_bounds_a_run_and_a_full_batch_is_logged(
    sm: sessionmaker[Session],
) -> None:
    teacher = _teacher(sm)
    students = [_student_seat(sm, teacher)[0] for _ in range(3)]
    with capture_logs() as logs:
        assert _monthly(sm, MONTH_START, limit=1) == 1
    (full,) = [e for e in logs if e["event"] == "seat_allowance_batch_full"]
    assert full["limit"] == 1
    assert sum(len(grants_of(sm, s)) for s in students) == 1
    assert _monthly(sm, MONTH_START, limit=10) == 2
    with capture_logs() as logs:
        assert _monthly(sm, MONTH_START, limit=10) == 0
    assert [e for e in logs if e["event"] == "seat_allowance_batch_full"] == []


def test_a_clawed_back_seat_grant_is_not_granted_again_nor_does_it_starve_the_batch(
    sm: sessionmaker[Session],
) -> None:
    """A clawback moves ``expires_at``; the seat's key still says it was granted this month."""
    teacher = _teacher(sm)
    refunded = add_user(sm, Role.student)
    refunded_seat = seed_seat(
        sm, teacher_id=teacher, student_id=refunded, created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    waiting, _ = _student_seat(sm, teacher)
    grant = _on_claim(sm, refunded_seat, MONTH_START)
    assert grant is not None
    with sm.begin() as session:
        assert UsageLedger(session).claw_back_grant(grant.id, reason="refund", now=MONTH_START) > 0
    # The clawed-back seat sorts first; with limit=1 it must not take the slot or be counted.
    assert _monthly(sm, MONTH_START, limit=1) == 1
    assert len(grants_of(sm, waiting)) == 1
    for _ in range(3):
        assert _monthly(sm, MONTH_START) == 0
    assert len(grants_of(sm, refunded)) == 1


def test_a_second_job_instance_with_a_stale_candidate_list_counts_nothing(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two instances read the same candidates; the loser finds stored grants and counts 0."""
    teacher = _teacher(sm)
    seats = [_student_seat(sm, teacher)[1] for _ in range(3)]
    stale = list(seats)
    monkeypatch.setattr(seat_allowance_repo, "_seats_lacking_a_grant", lambda *a, **k: stale)
    assert _monthly(sm, MONTH_START) == 3  # the winner
    assert _monthly(sm, MONTH_START) == 0  # the loser: the same ids, already granted
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(UsageGrant)) == 3


def test_the_job_query_skips_seats_that_are_not_active(sm: sessionmaker[Session]) -> None:
    """A leaving or removed seat sorted first must not take the only batch slot."""
    teacher = _teacher(sm)
    early = datetime(2026, 1, 1, tzinfo=UTC)
    for status in (TeacherMemberStatus.leaving, TeacherMemberStatus.removed):
        seed_seat(
            sm,
            teacher_id=teacher,
            student_id=add_user(sm, Role.student),
            status=status,
            created_at=early,
        )
    active, _ = _student_seat(sm, teacher)
    assert _monthly(sm, MONTH_START, limit=1) == 1
    assert len(grants_of(sm, active)) == 1


def test_the_default_batch_is_five_hundred() -> None:
    assert SEAT_GRANT_BATCH == 500


# ── the claim hook ──────────────────────────────────────────────────────────


def test_a_class_join_claim_issues_the_prorated_seat_allowance(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm)
    student = add_user(sm, Role.student)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code=None)
    member = _claim(sm, class_id, student, NOV_15)
    [grant] = grants_of(sm, student)
    assert grant.kind is GrantKind.seat_allowance
    assert (grant.teacher_member_id, grant.units) == (member.id, 160)
    assert grant.idempotency_key == f"seat:{member.id}:2026-11"


def test_a_claim_on_a_reused_seat_issues_nothing_twice(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm)
    student = add_user(sm, Role.student)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code=None)
    other_class, _ = add_class(sm, teacher_id=teacher, subject_code=None)
    _claim(sm, class_id, student, NOV_15)
    _claim(sm, other_class, student, NOV_30)
    assert len(grants_of(sm, student)) == 1


def test_a_failing_grant_never_refuses_the_class_join(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher = _teacher(sm)
    student = add_user(sm, Role.student)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code=None)
    _fail_with_a_database_error(monkeypatch, {student})

    with capture_logs() as logs:
        member = _claim(sm, class_id, student, NOV_15)

    with sm() as session:
        seat = session.get(TeacherMember, member.id)
        assert seat is not None
        assert (seat.kind, seat.status) == (
            TeacherMemberKind.student_seat,
            TeacherMemberStatus.active,
        )
    assert grants_of(sm, student) == []
    (alert,) = [e for e in logs if e["event"] == "seat_allowance_grant_failed"]
    assert (alert["log_level"], alert["alert"]) == ("error", True)
    assert alert["teacher_member_id"] == str(member.id)

    monkeypatch.undo()  # the monthly job repairs it on the next tick, same prorated amount
    assert _monthly(sm, NOV_15) == 1
    [grant] = grants_of(sm, student)
    assert (grant.teacher_member_id, grant.units) == (member.id, 160)


def test_a_failing_grant_on_a_reused_seat_never_refuses_the_join_either(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher = _teacher(sm)
    student, seat = _student_seat(sm, teacher)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code=None)
    _fail_with_a_database_error(monkeypatch, {student})
    with capture_logs() as logs:
        assert _claim(sm, class_id, student, NOV_15).id == seat
    assert [
        e["teacher_member_id"] for e in logs if e["event"] == "seat_allowance_grant_failed"
    ] == [str(seat)]


def test_a_claim_without_a_seat_allowance_issues_no_grant(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm, units=0)
    student = add_user(sm, Role.student)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code=None)
    _claim(sm, class_id, student, NOV_15)
    assert grants_of(sm, student) == []
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(UsageGrant)) == 0


def test_a_leaving_seat_that_rejoins_gets_no_grant(sm: sessionmaker[Session]) -> None:
    teacher = _teacher(sm)
    student, _ = _student_seat(sm, teacher, TeacherMemberStatus.leaving)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code=None)
    _claim(sm, class_id, student, NOV_15)
    assert grants_of(sm, student) == []
