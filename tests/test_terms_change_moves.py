"""Plan terms changes reach existing subscribers at their next renewal, after a notice (UD13-A).

Real Postgres (a throwaway ``create_all`` database). The notice job stamps a pending move and
queues one email (no amount, UD13-E); the amount sweep PUTs the new amount; a renewal charged at
that amount moves the subscriber, and one charged at the old amount is accepted and defers the
move. On the fixed-amount path (Paymob cannot change the amount) a move that changes the amount
cancels the plan at its period end instead, and one that does not applies at the renewal.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.db.models.billing import (
    PlanAudience,
    PlanTier,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.usage import GrantKind
from lemely.db.plan_terms_repo import (
    first_applies_at,
    fixed_path_move_ids,
    queue_terms_change_notices,
)
from lemely.db.subscription_repo import TRIGGER_SUCCESS, SubscriptionService
from lemely.db.teacher_team_repo import TeacherTeamService
from lemely.web.subscription_deps import SubscriptionDeps
from lemely.web.subscription_jobs import terms_change_notices_job, terms_move_fixed_path_job
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    charge,
    edit_tier_terms,
    ensure_billing_settings,
    grants_of,
    paymob_settings,
    remote_subscription,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    subscription_webhook,
    throwaway_database,
)
from tests.team_db import emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

PID = 4321
END = T0 + timedelta(days=30)
NOW0 = T0 + timedelta(days=1)  # the notice tick
NOTICE = timedelta(days=14)  # billing_settings.price_change_notice_days, default (UD13-G)


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def sm(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(_database)
    with _database.begin() as session:
        session.execute(sa.text("TRUNCATE paymob_events CASCADE"))
    ensure_billing_settings(_database)


def _linked(
    sm: sessionmaker[Session],
    tier: uuid.UUID,
    *,
    amount: int = 10_000,
    user: uuid.UUID | None = None,
    **kwargs: Any,
) -> tuple[uuid.UUID, uuid.UUID]:
    """``(owner, subscription)``: a paid, Paymob-linked plan on terms version 1."""
    owner = user or seed_user(sm, Role.student)
    options: dict[str, Any] = {
        "payer_id": owner,
        "paymob_subscription_id": PID,
        "paymob_amount_minor": amount,
        "activated_at": T0,
    } | kwargs
    return owner, seed_subscription(sm, user_id=owner, tier_id=tier, **options)


def _sub(sm: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, sid)
        assert row is not None
        return row


def _mail(sm: sessionmaker[Session], recipient: uuid.UUID) -> list[EmailOutbox]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(EmailOutbox)
                .where(
                    EmailOutbox.recipient_user_id == recipient,
                    EmailOutbox.template.in_(("plan_terms_change", "plan_terms_ends")),
                )
                .order_by(EmailOutbox.created_at, EmailOutbox.id)
            )
        )


def _notify(sm: sessionmaker[Session], *, now: datetime = NOW0, updatable: bool = True) -> int:
    return queue_terms_change_notices(sm, now=now, amount_updatable=updatable)


def _service(
    session: Session, client: FakePaymobClient, *, updatable: bool = True
) -> SubscriptionService:
    return SubscriptionService(
        session, client, paymob_settings(subscription_amount_updatable=updatable)
    )


def _renew(
    sm: sessionmaker[Session],
    amount: int,
    *,
    txn: int = 888,
    at: datetime = END,
    updatable: bool = True,
) -> None:
    client = FakePaymobClient()
    client.subscriptions[PID] = remote_subscription(PID, amount_cents=amount)
    client.last_transactions[PID] = charge(txn, amount, created_at=at - timedelta(hours=2))
    with sm.begin() as session:
        _service(session, client, updatable=updatable).apply_renewal_webhook(
            subscription_webhook(TRIGGER_SUCCESS, PID), now=at + timedelta(minutes=5)
        )


def _sweep(sm: sessionmaker[Session], now: datetime) -> FakePaymobClient:
    client = FakePaymobClient()
    client.subscriptions[PID] = remote_subscription(PID)
    with sm() as session:
        _service(session, client).apply_period_end_changes(now=now)
    return client


def _period_grants(sm: sessionmaker[Session], owner: uuid.UUID) -> list[int]:
    return [g.units for g in grants_of(sm, owner) if g.kind is GrantKind.period_allowance]


def _periods(sm: sessionmaker[Session], sid: uuid.UUID) -> list[SubscriptionPeriod]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(SubscriptionPeriod)
                .where(SubscriptionPeriod.subscription_id == sid)
                .order_by(SubscriptionPeriod.period_start)
            )
        )


# -- the notice -------------------------------------------------------------------------


def test_a_worse_change_waits_the_full_notice_period_and_sends_one_mail(
    sm: sessionmaker[Session],
) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    owner, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=14_000)
    assert _notify(sm) == 1
    sub = _sub(sm, sid)
    assert sub.pending_terms_version == 2
    assert sub.pending_terms_effective_at == NOW0 + NOTICE
    assert sub.terms_notice_sent_at == NOW0
    assert sub.terms_version == 1  # nothing moves until the renewal
    (mail,) = _mail(sm, owner)
    assert mail.template == "plan_terms_change"
    assert mail.context["price_changes"] is True
    assert "amount" not in " ".join(mail.context)  # UD13-E: no figure travels
    assert mail.dedupe_key == f"terms_change:{sid}:2"


def test_a_better_change_is_effective_at_once(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000, allowance_units=1_000)
    owner, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=8_000, allowance_units=2_000)
    _notify(sm)
    assert _sub(sm, sid).pending_terms_effective_at == NOW0
    assert len(_mail(sm, owner)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"allowance_units": 500},
        {"seat_allowance_units": 10},
    ],
)
def test_a_smaller_allowance_is_worse_even_at_the_same_price(
    sm: sessionmaker[Session], change: dict[str, int]
) -> None:
    tier = seed_tier(sm, allowance_units=1_000, seat_allowance_units=50)
    _, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, **change)
    _notify(sm)
    assert _sub(sm, sid).pending_terms_effective_at == NOW0 + NOTICE


def test_fewer_included_seats_is_worse_and_the_mail_counts_the_students_to_remove(
    sm: sessionmaker[Session],
) -> None:
    teacher = seed_user(sm, Role.teacher)
    tier = seed_tier(sm, audience=PlanAudience.teacher, included_seats=5)
    _, sid = _linked(sm, tier, user=teacher, period_end=END)
    for _ in range(5):
        seed_seat(sm, teacher_id=teacher, student_id=seed_user(sm, Role.student))
    edit_tier_terms(sm, tier, included_seats=3)
    _notify(sm)
    assert _sub(sm, sid).pending_terms_effective_at == NOW0 + NOTICE
    (mail,) = _mail(sm, teacher)
    assert mail.context["seats_over"] == 2
    assert mail.context["entitlements_change"] is True


def test_the_notice_period_is_the_admin_setting(sm: sessionmaker[Session]) -> None:
    with sm.begin() as session:
        session.execute(sa.text("UPDATE billing_settings SET price_change_notice_days = 21"))
    tier = seed_tier(sm, price_minor=10_000)
    _, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=12_000)
    _notify(sm)
    assert _sub(sm, sid).pending_terms_effective_at == NOW0 + timedelta(days=21)


def test_a_second_edit_sends_a_second_notice_and_the_date_restarts(
    sm: sessionmaker[Session],
) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    owner, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=12_000)
    _notify(sm)
    later = NOW0 + timedelta(days=3)
    edit_tier_terms(sm, tier, price_minor=15_000)
    assert _notify(sm, now=later) == 1
    sub = _sub(sm, sid)
    assert (sub.pending_terms_version, sub.pending_terms_effective_at) == (3, later + NOTICE)
    assert [m.dedupe_key for m in _mail(sm, owner)] == [
        f"terms_change:{sid}:2",
        f"terms_change:{sid}:3",
    ]


def test_a_tick_with_nothing_new_changes_nothing(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    owner, _ = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=12_000)
    assert _notify(sm) == 1
    assert _notify(sm, now=NOW0 + timedelta(hours=1)) == 0
    assert len(_mail(sm, owner)) == 1


def test_a_cancelling_subscriber_gets_no_notice(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    owner, sid = _linked(sm, tier, period_end=END, cancel_at_period_end=True)
    edit_tier_terms(sm, tier, price_minor=14_000)
    assert _notify(sm) == 0
    assert _mail(sm, owner) == []
    assert _sub(sm, sid).pending_terms_version is None


def test_complimentary_manual_and_ended_plans_get_no_notice(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    complimentary = seed_user(sm, Role.student)
    seed_subscription(sm, user_id=complimentary, tier_id=tier, payer_id=None, period_end=END)
    manual = seed_user(sm, Role.student)
    seed_subscription(
        sm,
        user_id=manual,
        tier_id=tier,
        payer_id=manual,
        is_manually_activated=True,
        period_end=END,
    )
    ended = seed_user(sm, Role.student)
    seed_subscription(
        sm, user_id=ended, tier_id=tier, payer_id=ended, status=SubscriptionStatus.expired
    )
    edit_tier_terms(sm, tier, price_minor=14_000)
    assert _notify(sm) == 0
    assert [_mail(sm, u) for u in (complimentary, manual, ended)] == [[], [], []]


def test_a_past_due_plan_is_noticed(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    owner, _ = _linked(sm, tier, period_end=END, status=SubscriptionStatus.past_due)
    edit_tier_terms(sm, tier, price_minor=14_000)
    assert _notify(sm) == 1
    assert len(_mail(sm, owner)) == 1


def test_a_pending_downgrade_is_not_noticed_about_the_tier_it_leaves(
    sm: sessionmaker[Session],
) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    cheaper = seed_tier(sm, price_minor=5_000)
    owner, _ = _linked(sm, tier, period_end=END, pending_plan_tier_id=cheaper)
    edit_tier_terms(sm, tier, price_minor=14_000)
    assert _notify(sm) == 0
    assert _mail(sm, owner) == []


def test_a_change_the_subscriber_cannot_see_moves_without_a_mail(
    sm: sessionmaker[Session],
) -> None:
    tier = seed_tier(sm, price_minor=10_000, extra_seat_price_minor=0)
    owner, sid = _linked(sm, tier, period_end=END)
    # A seat price on a tier that sold none: the student holds no seats, so nothing changes.
    edit_tier_terms(sm, tier, extra_seat_price_minor=500)
    _notify(sm)
    assert _mail(sm, owner) == []
    sub = _sub(sm, sid)
    assert sub.pending_terms_version == 2
    assert sub.terms_notice_sent_at is None


def test_the_applies_date_is_the_first_period_end_on_or_after_the_effective_date() -> None:
    effective = NOW0 + NOTICE
    assert first_applies_at(END, "monthly", effective) == END  # T0+30d >= T0+15d
    near = NOW0 + timedelta(days=5)
    assert first_applies_at(near, "monthly", effective) == near + timedelta(days=30)
    assert first_applies_at(effective, "monthly", effective) == effective


def test_the_mail_names_the_renewal_date_not_the_notice_date(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    owner, _ = _linked(sm, tier, period_end=NOW0 + timedelta(days=5))
    edit_tier_terms(sm, tier, price_minor=14_000)
    _notify(sm)
    (mail,) = _mail(sm, owner)
    assert str(mail.context["applies_at"]).startswith(
        (NOW0 + timedelta(days=35)).strftime("%Y-%m-%dT%H:%M")
    )


def test_the_jobs_run_through_the_deps_bundle(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    owner, _ = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=14_000)
    deps = SubscriptionDeps(sm, FakePaymobClient(), paymob_settings())
    assert terms_change_notices_job(deps, now=NOW0) == 1
    assert len(_mail(sm, owner)) == 1


# -- the renewal move (updatable path) -------------------------------------------------


def test_the_new_amount_is_put_before_the_renewal_and_the_renewal_moves_the_subscriber(
    sm: sessionmaker[Session],
) -> None:
    tier = seed_tier(sm, price_minor=10_000, allowance_units=1_000)
    owner, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=14_000, allowance_units=5_000)
    _notify(sm)
    client = _sweep(sm, END - timedelta(days=1))
    assert [c["amount_cents"] for c in client.calls_to("update_subscription")] == [14_000]
    assert _sub(sm, sid).paymob_amount_minor == 14_000

    _renew(sm, 14_000)
    sub = _sub(sm, sid)
    assert (sub.terms_version, sub.pending_terms_version) == (2, None)
    assert sub.pending_terms_effective_at is None
    assert _periods(sm, sid)[-1].terms_version == 2
    assert _period_grants(sm, owner) == [5_000]


def test_a_renewal_before_the_move_is_effective_keeps_the_old_terms(
    sm: sessionmaker[Session],
) -> None:
    """The period ends before the notice period does: it renews on the old terms, move pending."""
    tier = seed_tier(sm, price_minor=10_000, allowance_units=1_000)
    owner, sid = _linked(sm, tier, period_end=NOW0 + timedelta(days=5))
    edit_tier_terms(sm, tier, price_minor=14_000, allowance_units=5_000)
    _notify(sm)
    assert _sweep(sm, NOW0 + timedelta(days=4)).calls_to("update_subscription") == []
    _renew(sm, 10_000, at=NOW0 + timedelta(days=5))
    sub = _sub(sm, sid)
    assert (sub.terms_version, sub.pending_terms_version) == (1, 2)
    assert _period_grants(sm, owner) == [1_000]


def test_a_renewal_at_the_old_amount_is_accepted_and_the_move_waits(
    sm: sessionmaker[Session],
) -> None:
    tier = seed_tier(sm, price_minor=10_000, allowance_units=1_000)
    owner, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=14_000, allowance_units=5_000)
    _notify(sm)
    with capture_logs() as logs:
        _renew(sm, 10_000)  # the PUT never happened: Paymob charged the stamp
    assert any(e["event"] == "subscription_terms_move_deferred" for e in logs)
    sub = _sub(sm, sid)
    assert (sub.terms_version, sub.pending_terms_version) == (1, 2)
    assert _periods(sm, sid)[-1].terms_version == 1
    assert _period_grants(sm, owner) == [1_000]

    # A later renewal, now charged at the pushed amount, moves the subscriber.
    _sweep(sm, END + timedelta(days=29))
    assert _sub(sm, sid).paymob_amount_minor == 14_000
    _renew(sm, 14_000, txn=889, at=END + timedelta(days=30))
    sub = _sub(sm, sid)
    assert (sub.terms_version, sub.pending_terms_version) == (2, None)
    assert _period_grants(sm, owner) == [1_000, 5_000]


def test_a_pending_plan_change_wins_over_the_terms_move(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    cheaper = seed_tier(sm, price_minor=6_000, allowance_units=300)
    edit_tier_terms(sm, cheaper, price_minor=6_500)  # the target's current terms are version 2
    _, sid = _linked(
        sm,
        tier,
        amount=6_500,
        period_end=END,
        pending_plan_tier_id=cheaper,
        pending_terms_version=None,
    )
    _renew(sm, 6_500)
    sub = _sub(sm, sid)
    assert sub.plan_tier_id == cheaper
    assert (sub.terms_version, sub.pending_terms_version) == (2, None)


def test_seats_are_not_cut_mid_period_and_are_shed_at_the_renewal(
    sm: sessionmaker[Session],
) -> None:
    teacher = seed_user(sm, Role.teacher)
    tier = seed_tier(sm, audience=PlanAudience.teacher, price_minor=10_000, included_seats=5)
    _, sid = _linked(sm, tier, user=teacher, period_end=END)
    for _ in range(5):
        seed_seat(sm, teacher_id=teacher, student_id=seed_user(sm, Role.student))
    edit_tier_terms(sm, tier, included_seats=3)
    _notify(sm)

    with sm() as session:
        assert TeacherTeamService(session).seat_capacity(teacher) == 5  # still, mid-period

    def seats(status: TeacherMemberStatus) -> int:
        with sm() as session:
            return int(
                session.scalar(
                    sa.select(sa.func.count())
                    .select_from(TeacherMember)
                    .where(TeacherMember.teacher_user_id == teacher, TeacherMember.status == status)
                )
                or 0
            )

    assert seats(TeacherMemberStatus.leaving) == 0
    _renew(sm, 10_000)  # the price is unchanged, so the move is applied at this renewal
    assert _sub(sm, sid).terms_version == 2
    with sm() as session:
        assert TeacherTeamService(session).seat_capacity(teacher) == 3
    assert seats(TeacherMemberStatus.leaving) == 2


# -- the fixed-amount path (UD-P4) -----------------------------------------------------


def test_a_price_rise_on_the_fixed_path_says_the_plan_ends(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    owner, _ = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=14_000)
    _notify(sm, updatable=False)
    (mail,) = _mail(sm, owner)
    assert mail.template == "plan_terms_ends"
    assert str(mail.context["ends_at"]).startswith(END.strftime("%Y-%m-%dT%H:%M"))


def test_the_fixed_path_job_cancels_at_period_end_and_never_puts_the_amount(
    sm: sessionmaker[Session],
) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    _, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=14_000)
    _notify(sm, updatable=False)
    client = FakePaymobClient()
    deps = SubscriptionDeps(sm, client, paymob_settings(subscription_amount_updatable=False))
    with capture_logs() as logs:
        assert terms_move_fixed_path_job(deps, now=NOW0) == 1
    assert any(e["event"] == "subscription_terms_move_cancel_scheduled" for e in logs)
    assert _sub(sm, sid).cancel_at_period_end is True
    assert client.calls == []  # no Paymob call: the cancel sweep pushes the cancel later
    assert terms_move_fixed_path_job(deps, now=NOW0) == 0  # already cancelling


def test_the_fixed_path_job_does_nothing_on_the_updatable_path(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    _, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=14_000)
    _notify(sm)
    deps = SubscriptionDeps(sm, FakePaymobClient(), paymob_settings())
    assert terms_move_fixed_path_job(deps, now=NOW0) == 0
    assert _sub(sm, sid).cancel_at_period_end is False


def test_an_allowance_only_change_on_the_fixed_path_moves_at_the_renewal(
    sm: sessionmaker[Session],
) -> None:
    tier = seed_tier(sm, price_minor=10_000, allowance_units=1_000)
    owner, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, allowance_units=4_000)
    _notify(sm, updatable=False)
    (mail,) = _mail(sm, owner)
    assert mail.template == "plan_terms_change"
    with sm() as session:
        assert fixed_path_move_ids(session, now=NOW0) == []
    _renew(sm, 10_000, updatable=False)
    sub = _sub(sm, sid)
    assert (sub.terms_version, sub.pending_terms_version) == (2, None)
    assert _period_grants(sm, owner) == [4_000]


def test_a_renewal_that_slips_through_on_the_fixed_path_never_applies_a_repricing_move(
    sm: sessionmaker[Session],
) -> None:
    tier = seed_tier(sm, price_minor=10_000, allowance_units=1_000)
    owner, sid = _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=14_000, allowance_units=5_000)
    _notify(sm, updatable=False)
    _renew(sm, 10_000, updatable=False)  # charged the stamp before the cancel took hold
    sub = _sub(sm, sid)
    assert (sub.terms_version, sub.pending_terms_version) == (1, 2)
    assert _period_grants(sm, owner) == [1_000]


def test_the_fixed_path_job_skips_a_move_not_yet_due_and_a_cancelling_row(
    sm: sessionmaker[Session],
) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    _, early = _linked(sm, tier, period_end=NOW0 + timedelta(days=5))  # ends before effective
    edit_tier_terms(sm, tier, price_minor=14_000)
    _notify(sm, updatable=False)
    with sm() as session:
        assert fixed_path_move_ids(session, now=NOW0) == []
    assert _sub(sm, early).cancel_at_period_end is False


def test_the_tier_row_is_untouched_by_the_notice(sm: sessionmaker[Session]) -> None:
    tier = seed_tier(sm, price_minor=10_000)
    _linked(sm, tier, period_end=END)
    edit_tier_terms(sm, tier, price_minor=14_000)
    _notify(sm)
    with sm() as session:
        row = session.get(PlanTier, tier)
        assert row is not None
        assert (row.terms_version, row.price_minor) == (2, 14_000)
