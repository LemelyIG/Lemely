"""Downgrade, cancel at period end and the period-end sweep (spec §2.6, §5.3; P05 T8).

Gate-proof mutations (each makes the named test fail) are listed in the task report.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.core.subscription_rules import AMOUNT_SYNC_WINDOW, expected_renewal_amount_minor
from lemely.db import subscription_repo
from lemely.db.models.billing import Payment, PaymentStatus, PlanAudience, Subscription
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.subscription_repo import (
    DowngradeUnavailable,
    InvalidPlanChange,
    SeatsInsufficient,
    SubscriptionNotFound,
    SubscriptionService,
)
from lemely.io.paymob.client import PaymobError
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    charge,
    paymob_settings,
    remote_subscription,
    seed_first_payment,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    subscription_webhook,
    throwaway_database,
)
from tests.team_db import add_assistant, emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from sqlalchemy.orm import Session, sessionmaker

PID = 4321
END = T0 + timedelta(days=30)
NOW = T0 + timedelta(days=10)
FALLBACK = {"subscription_amount_updatable": False}


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def pg_sessionmaker(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(_database)
    with _database.begin() as session:
        session.execute(sa.text("TRUNCATE paymob_events CASCADE"))


# -- helpers ----------------------------------------------------------------------------


def _svc(
    session: Session, client: FakePaymobClient | None = None, **settings: Any
) -> SubscriptionService:
    return SubscriptionService(session, client or FakePaymobClient(), paymob_settings(**settings))


def _student_sub(
    sm: sessionmaker[Session], pid: int | None = PID, **kwargs: Any
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """``(payer, tier, subscription)``: a 100.00 student plan that pays for itself."""
    payer = seed_user(sm, Role.student)
    tier = seed_tier(sm, price_minor=10_000)
    options: dict[str, Any] = {
        "payer_id": payer,
        "paymob_subscription_id": pid,
        "paymob_amount_minor": 10_000,
        "activated_at": T0,
    } | kwargs
    return payer, tier, seed_subscription(sm, user_id=payer, tier_id=tier, **options)


def _sub(sm: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, sid)
        assert row is not None
        return row


def _sweep(
    sm: sessionmaker[Session],
    now: datetime,
    client: FakePaymobClient,
    **kwargs: Any,
) -> int:
    with sm() as session:
        return _svc(session, client).apply_period_end_changes(now=now, **kwargs)


def _notices(sm: sessionmaker[Session]) -> list[tuple[str, datetime]]:
    with sm() as session:
        rows = session.scalars(sa.select(EmailOutbox).order_by(EmailOutbox.created_at)).all()
        return [
            (str(r.context["notice"]), datetime.fromisoformat(str(r.context["effective_at"])))
            for r in rows
        ]


def _alerts(logs: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(entry["event"]) for entry in logs if entry.get("alert") is True]


def _puts(client: FakePaymobClient) -> list[tuple[int, int | None]]:
    return [
        (call["subscription_id"], call["amount_cents"])
        for call in client.calls_to("update_subscription")
    ]


def _deliver(
    sm: sessionmaker[Session], client: FakePaymobClient, trigger: str, now: datetime
) -> None:
    with sm.begin() as session:
        _svc(session, client).apply_renewal_webhook(subscription_webhook(trigger, PID), now=now)


def _remote(client: FakePaymobClient, pid: int = PID, state: str = "active") -> FakePaymobClient:
    client.subscriptions[pid] = remote_subscription(pid, state=state)
    return client


# -- IDOR: only the payer can change a plan ---------------------------------------------


def _outsider(
    sm: sessionmaker[Session], kind: str, teacher: uuid.UUID, child: uuid.UUID
) -> uuid.UUID:
    if kind == "child":
        return child
    if kind == "stranger":
        return seed_user(sm, Role.student)
    assistant = seed_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=teacher, assistant_id=assistant)
    return assistant


@pytest.mark.parametrize("who", ["child", "stranger", "assistant"])
@pytest.mark.parametrize("action", ["downgrade", "cancel"])
def test_only_the_payer_can_change_a_plan_and_everyone_else_sees_unknown_id(
    pg_sessionmaker: sessionmaker[Session], who: str, action: str
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    child = seed_user(pg_sessionmaker, Role.student)
    big = seed_tier(pg_sessionmaker, price_minor=50_000)
    lower = seed_tier(pg_sessionmaker, price_minor=30_000)
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=child,
        tier_id=big,
        payer_id=teacher,
        paymob_subscription_id=PID,
        paymob_amount_minor=50_000,
    )
    actor = _outsider(pg_sessionmaker, who, teacher, child)

    def attempt(subscription_id: uuid.UUID) -> SubscriptionNotFound:
        with pytest.raises(SubscriptionNotFound) as refused, pg_sessionmaker.begin() as session:
            svc = _svc(session)
            if action == "downgrade":
                svc.schedule_downgrade(
                    subscription_id, actor_user_id=actor, plan_tier_id=lower, now=NOW
                )
            else:
                svc.schedule_cancel(subscription_id, actor_user_id=actor, now=NOW)
        return refused.value

    unknown = uuid.uuid4()
    real, missing = attempt(sid), attempt(unknown)
    assert type(real) is type(missing)
    assert str(real).replace(str(sid), "ID") == str(missing).replace(str(unknown), "ID")
    after = _sub(pg_sessionmaker, sid)
    assert (after.pending_plan_tier_id, after.cancel_at_period_end) == (None, False)


def test_the_payer_who_is_not_the_beneficiary_can_change_the_plan(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.student)
    child = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, price_minor=10_000)
    sid = seed_subscription(
        pg_sessionmaker, user_id=child, tier_id=tier, payer_id=parent, paymob_subscription_id=PID
    )
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_cancel(sid, actor_user_id=parent, now=NOW)
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is True


# -- downgrade --------------------------------------------------------------------------


def test_downgrade_is_scheduled_then_pushed_once(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        _svc(session, client).schedule_downgrade(
            sid, actor_user_id=payer, plan_tier_id=lower, now=NOW
        )
    assert _sub(pg_sessionmaker, sid).pending_plan_tier_id == lower
    assert client.calls == []  # nothing at Paymob until the sweep

    assert _sweep(pg_sessionmaker, NOW, client) == 1
    assert _puts(client) == [(PID, 6_000)]
    sub = _sub(pg_sessionmaker, sid)
    assert sub.paymob_amount_minor == 6_000
    assert sub.plan_tier_id != lower  # the tier switches at renewal, not now

    assert _sweep(pg_sessionmaker, NOW, client) == 0
    assert len(client.calls) == 1


def test_choosing_the_current_tier_clears_a_pending_downgrade(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer, tier, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=tier, now=NOW)
    assert _sub(pg_sessionmaker, sid).pending_plan_tier_id is None


def test_a_cleared_downgrade_puts_the_original_amount_back_inside_the_window(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """DV-16: schedule, push, clear. The stamp (6 000) is stale, so the sweep repairs it, but
    only once the renewal is within ``AMOUNT_SYNC_WINDOW``: nothing pending selects nothing
    earlier."""
    payer, tier, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        _svc(session, client).schedule_downgrade(
            sid, actor_user_id=payer, plan_tier_id=lower, now=NOW
        )
    assert _sweep(pg_sessionmaker, NOW, client) == 1
    with pg_sessionmaker.begin() as session:
        _svc(session, client).schedule_downgrade(
            sid, actor_user_id=payer, plan_tier_id=tier, now=NOW
        )

    # Outside the window with nothing pending: left alone (no PUT).
    assert _sweep(pg_sessionmaker, END - AMOUNT_SYNC_WINDOW - timedelta(hours=1), client) == 0
    assert _puts(client) == [(PID, 6_000)]
    assert _sub(pg_sessionmaker, sid).paymob_amount_minor == 6_000

    # Inside it: the original price goes back to Paymob before the renewal charge.
    assert _sweep(pg_sessionmaker, END - AMOUNT_SYNC_WINDOW + timedelta(hours=1), client) == 1
    assert _puts(client) == [(PID, 6_000), (PID, 10_000)]
    assert _sub(pg_sessionmaker, sid).paymob_amount_minor == 10_000


def test_a_stamp_that_was_never_set_is_pushed(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, _, sid = _student_sub(pg_sessionmaker, paymob_amount_minor=None)
    client = FakePaymobClient()
    assert _sweep(pg_sessionmaker, NOW, client) == 1
    assert _puts(client) == [(PID, 10_000)]
    assert _sub(pg_sessionmaker, sid).paymob_amount_minor == 10_000


def test_downgrade_refusals(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker)
    refused = {
        "dearer": seed_tier(pg_sessionmaker, price_minor=20_000),
        "same price": seed_tier(pg_sessionmaker, price_minor=10_000),
        "other audience": seed_tier(
            pg_sessionmaker, audience=PlanAudience.teacher, price_minor=1_000
        ),
        "other interval": seed_tier(
            pg_sessionmaker, interval=PlanInterval.yearly, price_minor=1_000
        ),
        "inactive": seed_tier(pg_sessionmaker, price_minor=1_000, is_active=False),
        "other currency": seed_tier(pg_sessionmaker, price_minor=1_000, currency="USD"),
    }
    for name, target in refused.items():
        with (
            pytest.raises(InvalidPlanChange, match=r"."),
            pg_sessionmaker.begin() as session,
        ):
            _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=target, now=NOW)
        assert _sub(pg_sessionmaker, sid).pending_plan_tier_id is None, name
    with pytest.raises(InvalidPlanChange), pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(
            sid, actor_user_id=payer, plan_tier_id=uuid.uuid4(), now=NOW
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": SubscriptionStatus.past_due},
        {"status": SubscriptionStatus.cancelled},
        {"status": SubscriptionStatus.expired},
        {"cancel_at_period_end": True},
        {"is_manually_activated": True},
    ],
)
def test_downgrade_needs_an_active_card_subscription(
    pg_sessionmaker: sessionmaker[Session], kwargs: dict[str, Any]
) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker, **kwargs)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pytest.raises(InvalidPlanChange), pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)


def test_the_fallback_path_refuses_a_downgrade_but_clearing_and_cancelling_work(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Paymob cannot lower the amount: the old price would keep renewing, so refuse."""
    payer, tier, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    client = FakePaymobClient()
    with pytest.raises(DowngradeUnavailable) as refused, pg_sessionmaker.begin() as session:
        _svc(session, client, **FALLBACK).schedule_downgrade(
            sid, actor_user_id=payer, plan_tier_id=lower, now=NOW
        )
    assert refused.value.code == "downgrade_unavailable"
    assert _sub(pg_sessionmaker, sid).pending_plan_tier_id is None
    assert client.calls == []

    with pg_sessionmaker.begin() as session:  # clearing (the current tier) stays allowed
        svc = _svc(session, client, **FALLBACK)
        svc.schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=tier, now=NOW)
        svc.schedule_cancel(sid, actor_user_id=payer, now=NOW)
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is True
    assert client.calls == []


def test_teacher_downgrade_refused_until_the_seats_fit(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """UD-5: active, non-leaving seats must fit the new plan; a leaving seat does not count."""
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    big = seed_tier(
        pg_sessionmaker, audience=PlanAudience.teacher, price_minor=50_000, included_seats=10
    )
    small = seed_tier(
        pg_sessionmaker, audience=PlanAudience.teacher, price_minor=30_000, included_seats=3
    )
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=teacher,
        tier_id=big,
        payer_id=teacher,
        paymob_subscription_id=PID,
        paymob_amount_minor=50_000,
    )
    for _ in range(3):
        seed_seat(
            pg_sessionmaker, teacher_id=teacher, student_id=seed_user(pg_sessionmaker, Role.student)
        )
    fourth = seed_seat(
        pg_sessionmaker, teacher_id=teacher, student_id=seed_user(pg_sessionmaker, Role.student)
    )
    with pytest.raises(SeatsInsufficient) as refused, pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=teacher, plan_tier_id=small, now=NOW)
    assert (refused.value.in_use, refused.value.capacity) == (4, 3)

    with pg_sessionmaker.begin() as session:  # the fourth seat is on its way out
        session.execute(
            sa.text("UPDATE teacher_members SET status = 'leaving', leaves_at = :t WHERE id = :m"),
            {"m": fourth, "t": END},
        )
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=teacher, plan_tier_id=small, now=NOW)
    assert _sub(pg_sessionmaker, sid).pending_plan_tier_id == small


def test_a_downgrade_to_a_plan_that_sells_no_seats_is_refused_while_seats_are_held(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """DV-7: "no extra seats" is a price of 0, never ``None``."""
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    big = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=50_000,
        included_seats=10,
        extra_seat_price_minor=2_500,
    )
    plain = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=30_000,
        included_seats=10,
        extra_seat_price_minor=0,
    )
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=teacher,
        tier_id=big,
        payer_id=teacher,
        paymob_subscription_id=PID,
        paymob_amount_minor=57_500,
        extra_seats=3,
    )
    with pytest.raises(InvalidPlanChange), pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=teacher, plan_tier_id=plain, now=NOW)
    with pg_sessionmaker.begin() as session:  # none held (pending reduction to 0): allowed
        session.get(Subscription, sid).pending_extra_seats = 0  # type: ignore[union-attr]
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=teacher, plan_tier_id=plain, now=NOW)
    assert _sub(pg_sessionmaker, sid).pending_plan_tier_id == plain


# -- cancel -----------------------------------------------------------------------------


def test_cancel_is_pushed_on_the_next_sweep_and_ends_at_period_end_with_a_notice(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker)
    client = _remote(FakePaymobClient())
    with pg_sessionmaker.begin() as session:
        _svc(session, client).schedule_cancel(sid, actor_user_id=payer, now=NOW)
    assert client.calls == []  # scheduling makes no Paymob call
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is True

    assert _sweep(pg_sessionmaker, NOW, client) == 1
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.paymob_cancelled_at) == (SubscriptionStatus.active, NOW)
    assert client.names() == ["cancel_subscription"]

    # Access runs to the period end, then the plan is cancelled and the payer is told.
    assert _sweep(pg_sessionmaker, END - timedelta(seconds=1), client) == 0
    assert _notices(pg_sessionmaker) == []
    assert _sweep(pg_sessionmaker, END, client) == 1
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.cancelled
    assert client.names() == ["cancel_subscription"]
    assert _notices(pg_sessionmaker) == [("cancelled", END)]
    assert _sweep(pg_sessionmaker, END + timedelta(days=1), client) == 0
    assert _notices(pg_sessionmaker) == [("cancelled", END)]


def test_cancel_scheduling_drops_a_pending_downgrade(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_cancel(sid, actor_user_id=payer, now=NOW)
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.pending_plan_tier_id, sub.cancel_at_period_end) == (None, True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": SubscriptionStatus.expired},
        {"status": SubscriptionStatus.cancelled},
        {"is_manually_activated": True},
    ],
)
def test_cancel_is_refused_for_ended_and_manual_plans(
    pg_sessionmaker: sessionmaker[Session], kwargs: dict[str, Any]
) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker, **kwargs)
    with pytest.raises(InvalidPlanChange), pg_sessionmaker.begin() as session:
        _svc(session).schedule_cancel(sid, actor_user_id=payer, now=NOW)
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is False


def test_a_system_caller_can_cancel_without_a_paymob_call(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The fixed-amount terms move (P07 T16) cancels as the system: no payer, no Paymob write."""
    _, _, sid = _student_sub(pg_sessionmaker)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        _svc(session, client).schedule_cancel_as_system(sid, now=NOW)
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is True
    assert client.calls == []


def test_the_payer_methods_refuse_a_missing_actor_so_a_route_cannot_reach_the_system_path(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-6: ``None`` is not a payer; only the explicitly named system method skips the check."""
    _, _, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pytest.raises(TypeError), pg_sessionmaker.begin() as session:
        _svc(session).schedule_cancel(sid, actor_user_id=None, now=NOW)  # type: ignore[arg-type]
    with (
        pytest.raises(TypeError),
        pg_sessionmaker.begin() as session,
    ):
        _svc(session).schedule_downgrade(
            sid,
            actor_user_id=None,  # type: ignore[arg-type]
            plan_tier_id=lower,
            now=NOW,
        )
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.cancel_at_period_end, sub.pending_plan_tier_id) == (False, None)


def test_an_expired_linked_row_with_no_cancel_stamp_gets_its_cancel_pushed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """DV-27 / DV-15 fourth set: a Failed Overdue Transaction expired the row without a cancel,
    and a cancel that failed at expiry is retried, until Paymob stamps it."""
    _, _, overdue = _student_sub(pg_sessionmaker, pid=1, status=SubscriptionStatus.expired)
    _, _, cancelled = _student_sub(pg_sessionmaker, pid=2, status=SubscriptionStatus.cancelled)
    _, _, stamped = _student_sub(
        pg_sessionmaker, pid=3, status=SubscriptionStatus.expired, paymob_cancelled_at=T0
    )
    _, _, complimentary = _student_sub(pg_sessionmaker, pid=None, status=SubscriptionStatus.expired)
    client = FakePaymobClient()
    client.fail_for[("cancel_subscription", 1)] = PaymobError("down", status_code=502)
    assert _sweep(pg_sessionmaker, NOW, client) == 1  # row 2 only; row 1's cancel fails
    assert _sub(pg_sessionmaker, overdue).paymob_cancelled_at is None
    assert _sub(pg_sessionmaker, cancelled).paymob_cancelled_at == NOW
    del client.fail_for[("cancel_subscription", 1)]
    assert _sweep(pg_sessionmaker, NOW + timedelta(hours=1), client) == 1  # the retry
    assert _sub(pg_sessionmaker, overdue).paymob_cancelled_at == NOW + timedelta(hours=1)
    assert _sweep(pg_sessionmaker, NOW + timedelta(hours=2), client) == 0
    assert _sub(pg_sessionmaker, stamped).paymob_cancelled_at == T0
    assert _sub(pg_sessionmaker, complimentary).paymob_cancelled_at is None
    assert client.names().count("cancel_subscription") == 3
    assert _notices(pg_sessionmaker) == []  # these plans ended before: no notice from here


def test_a_never_activated_converted_row_is_cancelled_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """UD-3: the extra Paymob subscription of a credits-converted checkout is cancelled, and a
    row with no period (``NULL`` end) goes before the ones with a deadline."""
    _, _, dated = _student_sub(pg_sessionmaker, pid=1, status=SubscriptionStatus.expired)
    _, _, converted = _student_sub(
        pg_sessionmaker,
        pid=2,
        status=SubscriptionStatus.expired,
        period_start=None,
        period_end=None,
        activated_at=None,
    )
    client = FakePaymobClient()
    assert _sweep(pg_sessionmaker, NOW, client, limit=1) == 1
    assert _sub(pg_sessionmaker, converted).paymob_cancelled_at == NOW
    assert _sub(pg_sessionmaker, dated).paymob_cancelled_at is None
    assert client.calls_to("cancel_subscription") == [{"subscription_id": 2}]


def test_a_cancel_that_fails_is_retried_for_a_live_row_too(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker)
    client = _remote(FakePaymobClient())
    client.fail["cancel_subscription"] = PaymobError("down", status_code=503)
    with pg_sessionmaker.begin() as session:
        _svc(session, client).schedule_cancel(sid, actor_user_id=payer, now=NOW)
    assert _sweep(pg_sessionmaker, NOW, client) == 0
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at is None
    del client.fail["cancel_subscription"]
    assert _sweep(pg_sessionmaker, NOW + timedelta(hours=1), client) == 1
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at == NOW + timedelta(hours=1)


def test_the_sweep_is_bounded(pg_sessionmaker: sessionmaker[Session]) -> None:
    for pid in (1, 2, 3):
        payer, _, sid = _student_sub(pg_sessionmaker, pid=pid, cancel_at_period_end=True)
    client = FakePaymobClient()
    assert _sweep(pg_sessionmaker, NOW, client, limit=2) == 2
    assert _sweep(pg_sessionmaker, NOW, client, limit=2) == 1
    with pytest.raises(ValueError, match="limit"):
        _sweep(pg_sessionmaker, NOW, client, limit=0)


# -- UD-4 (b): a cancel made in Paymob, and a suspension, end as "cancelled" ---------------


def test_a_cancel_made_in_the_paymob_dashboard_ends_at_period_end_with_a_notice(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, _, sid = _student_sub(pg_sessionmaker)
    client = _remote(FakePaymobClient(), state="canceled")
    _deliver(pg_sessionmaker, client, subscription_repo.TRIGGER_CANCELED, NOW)
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.cancel_at_period_end, sub.paymob_cancelled_at) == (
        SubscriptionStatus.active,
        True,
        NOW,
    )
    assert _notices(pg_sessionmaker) == []  # past tense: nothing until the period ends
    assert _sweep(pg_sessionmaker, NOW, client) == 0  # nothing to push: Paymob already cancelled
    assert client.calls_to("cancel_subscription") == []
    assert _sweep(pg_sessionmaker, END, client) == 1
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.cancelled
    assert _notices(pg_sessionmaker) == [("cancelled", END)]


def test_a_suspension_is_a_cancel_at_period_end_with_the_same_notice(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The sweep would otherwise push a permanent Paymob cancel for a plan that was only
    suspended and tell nobody (P05-T7 review M-5)."""
    _, _, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        session.get(Subscription, sid).pending_plan_tier_id = lower  # type: ignore[union-attr]
    client = _remote(FakePaymobClient(), state="suspended")
    _deliver(pg_sessionmaker, client, subscription_repo.TRIGGER_SUSPENDED, NOW)
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.cancel_at_period_end, sub.pending_plan_tier_id) == (
        SubscriptionStatus.active,
        True,
        lower,  # M-4: the chosen downgrade is kept, so a resume restores it
    )
    assert _notices(pg_sessionmaker) == []
    # I-3: the cancel waits for the period end, so a resume can still undo it.
    assert _sweep(pg_sessionmaker, NOW, client) == 0
    assert client.calls_to("cancel_subscription") == []
    assert _sweep(pg_sessionmaker, END, client) == 2  # the cancel is pushed, then the plan ends
    assert client.calls_to("cancel_subscription") == [{"subscription_id": PID}]
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.suspended_at) == (SubscriptionStatus.cancelled, None)  # M-2
    assert _notices(pg_sessionmaker) == [("cancelled", END)]


def test_a_resume_before_the_period_end_undoes_the_cancel_its_suspension_caused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Paymob bills again after a resume: the plan must not be ended while it is charged."""
    _, _, sid = _student_sub(pg_sessionmaker)
    client = _remote(FakePaymobClient(), state="suspended")
    _deliver(pg_sessionmaker, client, subscription_repo.TRIGGER_SUSPENDED, NOW)
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is True
    resumed = _remote(FakePaymobClient(), state="active")
    _deliver(pg_sessionmaker, resumed, subscription_repo.TRIGGER_RESUMED, NOW + timedelta(hours=1))
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.cancel_at_period_end, sub.suspended_at) == (
        SubscriptionStatus.active,
        False,
        None,
    )
    assert _sweep(pg_sessionmaker, END, resumed) == 0  # nothing to push, nothing to end
    assert resumed.calls_to("cancel_subscription") == []
    assert _notices(pg_sessionmaker) == []


def test_a_cancel_the_payer_asked_for_survives_a_suspension_and_a_resume(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_cancel(sid, actor_user_id=payer, now=NOW)
    _deliver(
        pg_sessionmaker,
        _remote(FakePaymobClient(), state="suspended"),
        subscription_repo.TRIGGER_SUSPENDED,
        NOW + timedelta(hours=1),
    )
    assert _sub(pg_sessionmaker, sid).suspended_at is None  # not this suspension's cancel
    _deliver(
        pg_sessionmaker,
        _remote(FakePaymobClient(), state="active"),
        subscription_repo.TRIGGER_RESUMED,
        NOW + timedelta(hours=2),
    )
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.cancel_at_period_end) == (SubscriptionStatus.active, True)


def test_a_payer_cancel_after_a_suspension_survives_the_resume(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker)
    _deliver(
        pg_sessionmaker,
        _remote(FakePaymobClient(), state="suspended"),
        subscription_repo.TRIGGER_SUSPENDED,
        NOW,
    )
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_cancel(sid, actor_user_id=payer, now=NOW + timedelta(hours=1))
    assert _sub(pg_sessionmaker, sid).suspended_at is None
    _deliver(
        pg_sessionmaker,
        _remote(FakePaymobClient(), state="active"),
        subscription_repo.TRIGGER_RESUMED,
        NOW + timedelta(hours=2),
    )
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is True


@pytest.mark.parametrize("ended_by", ["pushed_cancel", "plan_ended"])
def test_a_resume_after_the_paymob_cancel_was_pushed_alerts_and_keeps_the_row_ended(
    pg_sessionmaker: sessionmaker[Session], ended_by: str
) -> None:
    _, _, sid = _student_sub(pg_sessionmaker)
    client = _remote(FakePaymobClient(), state="suspended")
    _deliver(pg_sessionmaker, client, subscription_repo.TRIGGER_SUSPENDED, NOW)
    if ended_by == "pushed_cancel":
        with pg_sessionmaker.begin() as session:  # the push stamped but the end has not run yet
            row = session.get(Subscription, sid)
            assert row is not None
            row.paymob_cancelled_at = NOW
    else:
        with pg_sessionmaker.begin() as session:  # ended with the Paymob cancel never stamped
            row = session.get(Subscription, sid)
            assert row is not None
            row.status = SubscriptionStatus.cancelled
    with capture_logs() as logs:
        _deliver(
            pg_sessionmaker,
            _remote(FakePaymobClient(), state="active"),
            subscription_repo.TRIGGER_RESUMED,
            NOW + timedelta(hours=1),
        )
    assert _alerts(logs) == ["subscription_resumed_after_cancel"]
    sub = _sub(pg_sessionmaker, sid)
    assert sub.cancel_at_period_end is True
    assert sub.status is (
        SubscriptionStatus.active if ended_by == "pushed_cancel" else SubscriptionStatus.cancelled
    )


def test_a_resume_with_no_suspension_behind_it_changes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, _, sid = _student_sub(pg_sessionmaker)
    with capture_logs() as logs:
        _deliver(
            pg_sessionmaker,
            _remote(FakePaymobClient(), state="active"),
            subscription_repo.TRIGGER_RESUMED,
            NOW,
        )
    assert _alerts(logs) == []
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.cancel_at_period_end, sub.suspended_at) == (False, None)


def test_a_paymob_cancel_clears_the_suspension_marker(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, _, sid = _student_sub(pg_sessionmaker)
    _deliver(
        pg_sessionmaker,
        _remote(FakePaymobClient(), state="suspended"),
        subscription_repo.TRIGGER_SUSPENDED,
        NOW,
    )
    _deliver(
        pg_sessionmaker,
        _remote(FakePaymobClient(), state="canceled"),
        subscription_repo.TRIGGER_CANCELED,
        NOW + timedelta(hours=1),
    )
    assert _sub(pg_sessionmaker, sid).suspended_at is None


def test_a_suspension_after_the_period_end_is_ended_by_the_next_sweep(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, _, sid = _student_sub(pg_sessionmaker)
    client = _remote(FakePaymobClient(), state="suspended")
    late = END + timedelta(hours=5)
    _deliver(pg_sessionmaker, client, subscription_repo.TRIGGER_SUSPENDED, late)
    assert _sweep(pg_sessionmaker, late, client) == 2  # the cancel push and the end
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.cancelled
    assert _notices(pg_sessionmaker) == [("cancelled", END)]


def test_ending_a_cancelled_plan_needs_the_period_to_be_over_and_a_live_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, _, linked = _student_sub(pg_sessionmaker, pid=1, cancel_at_period_end=True)
    _, _, complimentary = _student_sub(pg_sessionmaker, pid=None, cancel_at_period_end=True)
    _, _, past_due = _student_sub(
        pg_sessionmaker,
        pid=3,
        cancel_at_period_end=True,
        status=SubscriptionStatus.past_due,
        grace_until=END + timedelta(days=3),
    )
    client = FakePaymobClient()
    assert _sweep(pg_sessionmaker, END - timedelta(minutes=1), client) == 2  # cancels pushed
    assert _sweep(pg_sessionmaker, END, client) == 2  # linked and past_due end; compliment. not
    assert _sub(pg_sessionmaker, linked).status is SubscriptionStatus.cancelled
    assert _sub(pg_sessionmaker, past_due).status is SubscriptionStatus.cancelled
    assert _sub(pg_sessionmaker, past_due).grace_until is None
    assert _sub(pg_sessionmaker, complimentary).status is SubscriptionStatus.active  # R15


# -- PUT outcomes -----------------------------------------------------------------------


def test_a_failed_put_keeps_the_change_pending_and_the_others_proceed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer1, _, sid1 = _student_sub(pg_sessionmaker, pid=1)
    payer2, _, sid2 = _student_sub(pg_sessionmaker, pid=2)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    for payer, sid in ((payer1, sid1), (payer2, sid2)):
        with pg_sessionmaker.begin() as session:
            _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    client = FakePaymobClient()
    client.fail_for[("update_subscription", 1)] = PaymobError("rejected", status_code=400)
    with capture_logs() as logs:
        assert _sweep(pg_sessionmaker, NOW, client) == 1
    assert _alerts(logs) == ["subscription_sweep_failed"]
    failed = _sub(pg_sessionmaker, sid1)
    assert (failed.paymob_amount_minor, failed.pending_plan_tier_id) == (10_000, lower)
    assert _sub(pg_sessionmaker, sid2).paymob_amount_minor == 6_000


@pytest.mark.parametrize(
    "error",
    [
        PaymobError("timeout", timeout=True),
        PaymobError("transport"),
        PaymobError("server", status_code=502),
    ],
)
def test_an_unknown_put_outcome_leaves_the_stamp_and_is_retried(
    pg_sessionmaker: sessionmaker[Session], error: PaymobError
) -> None:
    """The PUT may have landed; the stamp must not say so. It is idempotent: next pass again."""
    payer, _, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    client = FakePaymobClient()
    client.fail["update_subscription"] = error
    with capture_logs() as logs:
        assert _sweep(pg_sessionmaker, NOW, client) == 0
    assert _sub(pg_sessionmaker, sid).paymob_amount_minor == 10_000
    assert _alerts(logs) == []  # not a sweep failure: nothing is rolled back or paged
    assert any(entry["event"] == "paymob_amount_put_unknown" for entry in logs)
    del client.fail["update_subscription"]
    assert _sweep(pg_sessionmaker, NOW + timedelta(hours=1), client) == 1
    assert _sub(pg_sessionmaker, sid).paymob_amount_minor == 6_000
    assert _puts(client) == [(PID, 6_000), (PID, 6_000)]


def test_a_pending_seat_reduction_is_pushed(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=50_000,
        included_seats=10,
        extra_seat_price_minor=2_500,
    )
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=teacher,
        tier_id=tier,
        payer_id=teacher,
        paymob_subscription_id=PID,
        paymob_amount_minor=57_500,
        extra_seats=3,
        pending_extra_seats=1,
    )
    client = FakePaymobClient()
    assert _sweep(pg_sessionmaker, NOW, client) == 1
    assert _puts(client) == [(PID, 52_500)]
    assert _sub(pg_sessionmaker, sid).paymob_amount_minor == 52_500


def test_the_amount_sweep_skips_cancelled_ended_and_complimentary_rows(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    _student_sub(pg_sessionmaker, pid=1, cancel_at_period_end=True, pending_plan_tier_id=lower)
    _student_sub(
        pg_sessionmaker, pid=2, status=SubscriptionStatus.past_due, pending_plan_tier_id=lower
    )
    _student_sub(pg_sessionmaker, pid=None, pending_plan_tier_id=lower)
    client = FakePaymobClient()
    sweep = _sweep(pg_sessionmaker, NOW, client)
    assert sweep == 1  # only row 1's cancel push
    assert _puts(client) == []


def test_sync_renewal_amount_is_a_no_op_without_a_link_or_a_difference(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, _, linked = _student_sub(pg_sessionmaker, pid=1)
    _, _, unlinked = _student_sub(pg_sessionmaker, pid=None, paymob_amount_minor=None)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        svc = _svc(session, client)
        assert svc.sync_renewal_amount(session.get(Subscription, linked)) is False  # type: ignore[arg-type]
        assert svc.sync_renewal_amount(session.get(Subscription, unlinked)) is False  # type: ignore[arg-type]
    assert client.calls == []


def test_the_fallback_path_never_puts_an_amount(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Paymob keeps charging the stamp, so a stamp is the expected amount and nothing is PUT."""
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    _, _, stamped = _student_sub(pg_sessionmaker, pid=1, pending_plan_tier_id=lower)
    _, _, unstamped = _student_sub(pg_sessionmaker, pid=2, paymob_amount_minor=None)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        fallback = _svc(session, client, **FALLBACK)
        updatable = _svc(session, client)
        row = session.get(Subscription, stamped)
        assert row is not None
        assert fallback.next_renewal_amount(row) == 10_000
        assert updatable.next_renewal_amount(row) == 6_000
        other = session.get(Subscription, unstamped)
        assert other is not None
        assert fallback.sync_renewal_amount(other) is False
    assert _sweep_with(pg_sessionmaker, client, FALLBACK) == 0
    assert client.calls == []


def _sweep_with(
    sm: sessionmaker[Session], client: FakePaymobClient, settings: dict[str, Any]
) -> int:
    with sm() as session:
        return _svc(session, client, **settings).apply_period_end_changes(now=NOW)


def test_the_pure_renewal_rule() -> None:
    def rule(*, seat_price: int = 500, stamp: int | None = 10_000, updatable: bool) -> int:
        return expected_renewal_amount_minor(
            price_minor=6_000,
            extra_seats=2,
            extra_seat_price_minor=seat_price,
            paymob_amount_minor=stamp,
            amount_updatable=updatable,
        )

    assert rule(updatable=True) == 7_000
    assert rule(updatable=False) == 10_000  # Paymob keeps charging the stamp
    assert rule(stamp=None, updatable=False) == 7_000  # nothing to hold fixed
    with pytest.raises(ValueError, match="no extra seats"):
        rule(seat_price=0, updatable=True)


# -- a plan change at renewal keeps the terms foreign key valid ---------------------------


def test_a_downgrade_applied_at_renewal_moves_to_the_target_tiers_terms(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """P07-T1 review M3: ``(plan_tier_id, terms_version)`` is a composite FK, so switching tier
    while keeping tier A's version 2 would fail the renewal. The target's current version is set
    and any pending move (to a version only tier A has) is cleared."""
    payer, tier_a, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO plan_tier_terms (plan_tier_id, terms_version, price_minor, "
                "extra_seat_price_minor, allowance_units, included_seats, seat_allowance_units) "
                "SELECT id, 2, price_minor, extra_seat_price_minor, allowance_units, "
                "included_seats, seat_allowance_units FROM plan_tiers WHERE id = :t"
            ),
            {"t": tier_a},
        )
        session.execute(
            sa.text("UPDATE plan_tiers SET terms_version = 2 WHERE id = :t"), {"t": tier_a}
        )
        session.execute(
            sa.text(
                "UPDATE subscriptions SET terms_version = 2, pending_terms_version = 2, "
                "pending_terms_effective_at = :e WHERE id = :s"
            ),
            {"t": tier_a, "e": END, "s": sid},
        )
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    client = _remote(FakePaymobClient())
    assert _sweep(pg_sessionmaker, NOW, client) == 1  # 6 000 reaches Paymob

    paid_at = END - timedelta(hours=2)
    client.last_transactions[PID] = charge(888, 6_000, created_at=paid_at)
    _deliver(pg_sessionmaker, client, subscription_repo.TRIGGER_SUCCESS, paid_at)

    sub = _sub(pg_sessionmaker, sid)
    assert sub.plan_tier_id == lower
    assert sub.terms_version == 1  # the target's current version, not tier A's 2
    assert (sub.pending_terms_version, sub.pending_terms_effective_at) == (None, None)
    assert sub.pending_plan_tier_id is None


# -- N-2: the last-charge floor (P05-T7 re-review) ----------------------------------------


def _failure_stands(sm: sessionmaker[Session], sid: uuid.UUID) -> bool:
    return _sub(sm, sid).status is SubscriptionStatus.past_due


def test_a_success_stamped_exactly_at_the_last_payment_does_not_confirm_payment(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Strictly newer is required: an equal timestamp fails safe (the failure stands)."""
    _, _, sid = _student_sub(pg_sessionmaker)
    paid_at = END - timedelta(hours=5)
    seed_first_payment(pg_sessionmaker, subscription_id=sid, paymob_txn_id=500, paid_at=paid_at)
    client = _remote(FakePaymobClient())
    client.last_transactions[PID] = charge(999, 10_000, created_at=paid_at)
    _deliver(pg_sessionmaker, client, subscription_repo.TRIGGER_FAILED, END - timedelta(hours=2))
    assert _failure_stands(pg_sessionmaker, sid)


def test_the_last_payment_not_the_period_start_is_the_floor_when_they_differ(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A mid-period payment is later than the period start: a success between the two is not
    newer than what is already recorded, so it proves nothing."""
    _, _, sid = _student_sub(pg_sessionmaker)
    seed_first_payment(
        pg_sessionmaker, subscription_id=sid, paymob_txn_id=500, paid_at=T0 + timedelta(days=5)
    )
    client = _remote(FakePaymobClient())
    client.last_transactions[PID] = charge(999, 10_000, created_at=T0 + timedelta(days=2))
    _deliver(pg_sessionmaker, client, subscription_repo.TRIGGER_FAILED, END - timedelta(hours=2))
    assert _failure_stands(pg_sessionmaker, sid)
    # Control: the same success, newer than the payment, does confirm it.
    _, _, other = _student_sub(pg_sessionmaker, pid=PID + 1)
    seed_first_payment(
        pg_sessionmaker, subscription_id=other, paymob_txn_id=501, paid_at=T0 + timedelta(days=5)
    )
    fresh = _remote(FakePaymobClient(), pid=PID + 1)
    fresh.last_transactions[PID + 1] = charge(998, 10_000, created_at=T0 + timedelta(days=6))
    with pg_sessionmaker.begin() as session:
        _svc(session, fresh).apply_renewal_webhook(
            subscription_webhook(subscription_repo.TRIGGER_FAILED, PID + 1),
            now=END - timedelta(hours=2),
        )
    assert not _failure_stands(pg_sessionmaker, other)


# -- review fixes (P05-T8 review) ---------------------------------------------------------


def _renewal_after(
    sm: sessionmaker[Session], *, sweep_between: bool
) -> tuple[uuid.UUID, Sequence[Mapping[str, Any]], FakePaymobClient]:
    """A downgrade is pending and never pushed; Paymob charges the old 10 000 at the period end."""
    payer, _, sid = _student_sub(sm)
    lower = seed_tier(sm, price_minor=6_000)
    with sm.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    client = _remote(FakePaymobClient())
    if sweep_between:
        # The sweep runs after Paymob charged but before its renewal webhook is processed.
        assert _sweep(sm, END + timedelta(minutes=5), client) == 0
    client.last_transactions[PID] = charge(888, 10_000, created_at=END)
    with capture_logs() as logs:
        _deliver(sm, client, subscription_repo.TRIGGER_SUCCESS, END + timedelta(minutes=10))
    return sid, logs, client


def _payments(sm: sessionmaker[Session]) -> list[tuple[int, PaymentStatus]]:
    with sm() as session:
        return [
            (p.amount_minor, p.status)
            for p in session.scalars(sa.select(Payment).order_by(Payment.created_at)).all()
        ]


@pytest.mark.parametrize("sweep_between", [False, True])
def test_a_sweep_after_paymob_charged_never_turns_the_paid_renewal_into_a_mismatch(
    pg_sessionmaker: sessionmaker[Session], sweep_between: bool
) -> None:
    """I-1: once the period is over the amount is not pushed, so the old-amount charge is paid."""
    sid, logs, client = _renewal_after(pg_sessionmaker, sweep_between=sweep_between)
    assert _puts(client) == []
    assert _payments(pg_sessionmaker) == [(10_000, PaymentStatus.paid)]
    assert _sub(pg_sessionmaker, sid).current_period_end > END  # type: ignore[operator]
    assert "subscription_renewal_mismatch" not in _alerts(logs)


def test_sync_renewal_amount_refuses_once_the_period_is_over_for_any_caller(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """I-1: P06's ``push_renewal_amount`` reaches Paymob through this method too."""
    payer, _, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        svc = _svc(session, client)
        row = session.get(Subscription, sid)
        assert row is not None
        assert svc.sync_renewal_amount(row, now=END) is False
        assert svc.sync_renewal_amount(row, now=END + timedelta(hours=1)) is False
        assert client.calls == []
        assert svc.sync_renewal_amount(row, now=END - timedelta(seconds=1)) is True
    assert _puts(client) == [(PID, 6_000)]


def test_rows_that_need_nothing_never_use_up_the_amount_limit(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """I-2: a row inside the window with a correct amount (earlier end) must not hide a pending
    change behind ``limit=1``."""
    _student_sub(pg_sessionmaker, pid=1, period_end=NOW + timedelta(hours=1))
    payer, _, sid_b = _student_sub(pg_sessionmaker, pid=2)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid_b, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    client = FakePaymobClient()
    assert _sweep(pg_sessionmaker, NOW, client, limit=1) == 1
    assert _puts(client) == [(2, 6_000)]
    assert _sub(pg_sessionmaker, sid_b).paymob_amount_minor == 6_000


def test_an_unknown_put_that_landed_is_repaired_after_the_downgrade_is_cleared(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-1: the stamp stays 10 000 and so does the expected amount, yet Paymob may hold 6 000."""
    payer, tier, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    client = FakePaymobClient()
    client.fail["update_subscription"] = PaymobError("timeout", timeout=True)
    assert _sweep(pg_sessionmaker, NOW, client) == 0
    del client.fail["update_subscription"]
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=tier, now=NOW)
    assert _sweep(pg_sessionmaker, NOW + timedelta(hours=1), client) == 1  # outside the window
    assert _puts(client) == [(PID, 6_000), (PID, 10_000)]
    assert _sweep(pg_sessionmaker, NOW + timedelta(hours=2), client) == 0  # certain again
    assert len(_puts(client)) == 2


def test_repeated_unknown_put_outcomes_page_after_three_in_a_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-7: a persistent fault with no HTTP status must not stay a warning forever."""
    payer, _, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    client = FakePaymobClient()
    client.fail["update_subscription"] = PaymobError("no route to host")
    paged: list[list[str]] = []
    for i in range(3):
        with capture_logs() as logs:
            assert _sweep(pg_sessionmaker, NOW + timedelta(minutes=i), client) == 0
        paged.append(_alerts(logs))
    assert paged == [[], [], ["paymob_amount_put_unknown_repeated"]]


def test_a_downgrade_must_lower_the_whole_renewal_amount_not_the_base_price(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-3: 100 + 5 x 10 = 150 to 90 + 5 x 20 = 190 is an upgrade, though the base is lower."""
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    current = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=10_000,
        included_seats=10,
        extra_seat_price_minor=1_000,
    )
    dearer_seats = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=9_000,
        included_seats=10,
        extra_seat_price_minor=2_000,
    )
    cheaper = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=9_000,
        included_seats=10,
        extra_seat_price_minor=1_000,
    )
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=teacher,
        tier_id=current,
        payer_id=teacher,
        paymob_subscription_id=PID,
        paymob_amount_minor=15_000,
        extra_seats=5,
    )
    with pytest.raises(InvalidPlanChange), pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(
            sid, actor_user_id=teacher, plan_tier_id=dearer_seats, now=NOW
        )
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=teacher, plan_tier_id=cheaper, now=NOW)
    assert _sub(pg_sessionmaker, sid).pending_plan_tier_id == cheaper


def test_a_sweep_between_suspension_and_resume_does_not_push_the_cancel(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """I-3 (and M-4): the undo survives routine sweeps, and the dropped downgrade comes back."""
    payer, _, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    client = _remote(FakePaymobClient(), state="suspended")
    _deliver(pg_sessionmaker, client, subscription_repo.TRIGGER_SUSPENDED, NOW)
    assert _sweep(pg_sessionmaker, NOW + timedelta(minutes=5), client) == 0
    assert client.calls_to("cancel_subscription") == []
    with capture_logs() as logs:
        _deliver(
            pg_sessionmaker,
            _remote(FakePaymobClient(), state="active"),
            subscription_repo.TRIGGER_RESUMED,
            NOW + timedelta(hours=1),
        )
    assert _alerts(logs) == []
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.cancel_at_period_end, sub.suspended_at, sub.pending_plan_tier_id) == (
        False,
        None,
        lower,
    )
    assert client.calls_to("cancel_subscription") == []


def test_ending_or_expiring_a_row_clears_the_suspension_marker(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-2: nothing can resume an ended plan, and the marker must not block 0058's downgrade."""
    _, _, ended = _student_sub(pg_sessionmaker, pid=1)
    _, _, lapsed = _student_sub(
        pg_sessionmaker,
        pid=2,
        status=SubscriptionStatus.past_due,
        grace_until=END + timedelta(days=3),
    )
    with pg_sessionmaker.begin() as session:
        for sid in (ended, lapsed):
            row = session.get(Subscription, sid)
            assert row is not None
            row.suspended_at = NOW
        ended_row = session.get(Subscription, ended)
        assert ended_row is not None
        ended_row.cancel_at_period_end = True
    client = FakePaymobClient()
    with pg_sessionmaker() as session:
        assert _svc(session, client).expire_overdue(now=END + timedelta(days=3)) == 1
    assert _sweep(pg_sessionmaker, END, client) >= 1
    for sid, status in (
        (ended, SubscriptionStatus.cancelled),
        (lapsed, SubscriptionStatus.expired),
    ):
        sub = _sub(pg_sessionmaker, sid)
        assert (sub.status, sub.suspended_at) == (status, None)


def test_failed_cancels_back_off_and_page_once_per_step(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-5: exponential, capped, and a backed-off row is neither retried nor counted."""
    _, _, sid = _student_sub(pg_sessionmaker, status=SubscriptionStatus.expired)
    client = FakePaymobClient()
    client.fail["cancel_subscription"] = PaymobError("down", status_code=503)
    attempts: list[datetime] = []
    paged: list[list[str]] = []
    now = NOW
    for _ in range(40):  # one sweep per simulated minute for 40 minutes
        before = len(client.calls_to("cancel_subscription"))
        with capture_logs() as logs:
            _sweep(pg_sessionmaker, now, client)
        if len(client.calls_to("cancel_subscription")) > before:
            attempts.append(now)
            paged.append(_alerts(logs))
        now += timedelta(minutes=1)
    # Tried at 0, +10 and +30 minutes (delays 10, 20, ...): not every sweep.
    assert attempts == [NOW, NOW + timedelta(minutes=10), NOW + timedelta(minutes=30)]
    assert paged == [[], ["subscription_cancel_retrying"], ["subscription_cancel_retrying"]]
    # A row that recovers is cancelled at its next try and forgotten.
    del client.fail["cancel_subscription"]
    assert _sweep(pg_sessionmaker, NOW + timedelta(hours=2), client) == 1
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at is not None


def test_a_backed_off_cancel_does_not_starve_the_rows_behind_it(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, _, stuck = _student_sub(
        pg_sessionmaker,
        pid=1,
        status=SubscriptionStatus.expired,
        period_start=None,
        period_end=None,
    )
    _, _, behind = _student_sub(pg_sessionmaker, pid=2, status=SubscriptionStatus.expired)
    client = FakePaymobClient()
    client.fail_for[("cancel_subscription", 1)] = PaymobError("down", status_code=503)
    assert _sweep(pg_sessionmaker, NOW, client, limit=1) == 0  # the NULL-period row goes first
    assert _sweep(pg_sessionmaker, NOW + timedelta(minutes=1), client, limit=1) == 1
    assert _sub(pg_sessionmaker, behind).paymob_cancelled_at is not None
    assert _sub(pg_sessionmaker, stuck).paymob_cancelled_at is None
