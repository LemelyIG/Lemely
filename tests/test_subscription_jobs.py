"""Phase 05 sweeper jobs: registered, ordered, isolated, recorded (spec §3 Jobs, DV-32)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from lemely.db.admin_health_repo import BILLING_JOB_NAMES
from lemely.db.announcement_repo import AnnouncementService
from lemely.db.billing_observability_repo import JobRunRecorder
from lemely.db.class_repo import ClassService
from lemely.db.models.billing import PlanAudience, Subscription
from lemely.db.models.billing_ops import JobRun
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.subscription_repo import SubscriptionService
from lemely.db.teacher_team_repo import TeacherTeamService
from lemely.io.paymob.client import PaymobClient
from lemely.runtime.config import NotificationsSettings, Settings
from lemely.web import deps, deps_billing, subscription_jobs
from lemely.web.push import RecordingPushTransport
from lemely.web.scheduled_notifications import Sweeper
from lemely.web.subscription_deps import SubscriptionDeps
from tests.subscription_fixtures import (
    FakePaymobClient,
    charge,
    grants_of,
    paymob_settings,
    remote_subscription,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    throwaway_database,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

DEC_1 = datetime(2026, 12, 1, 0, 1, tzinfo=UTC)
SUBSCRIPTION_JOBS = [
    "subscriptions.expire_overdue",
    "subscriptions.period_end",
    "subscriptions.drift_check",
]
SEAT_JOBS = ["seats.release_due", "seats.monthly_allowance"]
JOBS = [*SUBSCRIPTION_JOBS, *SEAT_JOBS]


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from _database()


def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


def _sweeper(
    sm: sessionmaker[Session],
    client: FakePaymobClient,
    now: datetime,
    *,
    with_subscriptions: bool = True,
    seat_allowances: bool = True,
    recorder: JobRunRecorder | None = None,
) -> Sweeper:
    return Sweeper(
        sessionmaker=sm,
        announcements=AnnouncementService(sm, ClassService(sm)),
        notifications=NotificationService(sm, NotificationPreferencesService(sm)),
        transport=RecordingPushTransport(),
        settings=NotificationsSettings(),
        now=lambda: now,
        subscriptions=SubscriptionDeps(sm, client, paymob_settings())
        if with_subscriptions
        else None,
        seat_allowances=seat_allowances,
        job_recorder=recorder,
    )


def test_jobs_run_in_dv32_order_after_the_existing_ones(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    results = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1).sweep_unbounded_for_tests()
    assert list(results)[-5:] == JOBS
    assert all(results[name] == 0 for name in JOBS)


def test_without_either_collaborator_the_job_set_is_unchanged(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    results = _sweeper(
        pg_sessionmaker,
        FakePaymobClient(),
        DEC_1,
        with_subscriptions=False,
        seat_allowances=False,
    ).sweep_unbounded_for_tests()
    assert not set(JOBS) & set(results)


def test_seat_jobs_run_without_paymob(pg_sessionmaker: sessionmaker[Session]) -> None:
    """DV-22: a manual teacher plan still gets its seats released and granted."""
    results = _sweeper(
        pg_sessionmaker, FakePaymobClient(), DEC_1, with_subscriptions=False
    ).sweep_unbounded_for_tests()
    assert list(results)[-2:] == SEAT_JOBS
    assert not set(SUBSCRIPTION_JOBS) & set(results)


def test_subscription_jobs_do_not_need_the_seat_flag(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    results = _sweeper(
        pg_sessionmaker, FakePaymobClient(), DEC_1, seat_allowances=False
    ).sweep_unbounded_for_tests()
    assert list(results)[-3:] == SUBSCRIPTION_JOBS
    assert not set(SEAT_JOBS) & set(results)


TERMS_JOBS = ["billing.terms_change_notices", "billing.terms_move_fixed_path"]


def test_the_terms_jobs_run_before_the_expiry_and_period_end_sweeps(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """UD13-A: announce, then schedule the fixed-path cancels, before the sweep pushes cancels."""
    results = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1).sweep_unbounded_for_tests()
    order = list(results)
    assert all(results[name] == 0 for name in TERMS_JOBS)
    assert order.index(TERMS_JOBS[0]) + 1 == order.index(TERMS_JOBS[1])
    assert order.index(TERMS_JOBS[1]) < order.index("subscriptions.expire_overdue")
    assert order.index(TERMS_JOBS[1]) < order.index("subscriptions.period_end")


def test_the_terms_jobs_need_the_subscription_collaborator_and_are_listed_for_health(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    results = _sweeper(
        pg_sessionmaker, FakePaymobClient(), DEC_1, with_subscriptions=False
    ).sweep_unbounded_for_tests()
    assert not set(TERMS_JOBS) & set(results)
    assert set(TERMS_JOBS) <= set(BILLING_JOB_NAMES)


def test_every_job_name_is_listed_for_admin_health() -> None:
    assert set(JOBS) | {"admin.expire_manual_subscriptions"} <= set(BILLING_JOB_NAMES)


def test_every_job_is_recorded_in_job_runs(pg_sessionmaker: sessionmaker[Session]) -> None:
    sweeper = _sweeper(
        pg_sessionmaker, FakePaymobClient(), DEC_1, recorder=JobRunRecorder(pg_sessionmaker)
    )
    results = sweeper.sweep_unbounded_for_tests()
    with pg_sessionmaker() as session:
        rows = {r.name: r for r in session.scalars(select(JobRun))}
    assert set(JOBS) <= set(rows)
    assert set(rows) == set(results)
    assert all(rows[name].last_outcome == "ok" for name in JOBS)


def test_a_job_that_throws_does_not_stop_the_others(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(
        self: SubscriptionService,
        *,
        now: datetime,
        limit: int = 1,
        should_stop: Callable[[], bool] | None = None,
    ) -> int:
        raise RuntimeError("paymob is down")

    monkeypatch.setattr(SubscriptionService, "expire_overdue", boom)
    results = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1).sweep_unbounded_for_tests()
    assert results["subscriptions.expire_overdue"] is None
    assert [results[name] for name in JOBS[1:]] == [0, 0, 0, 0]


def test_the_seat_allowance_job_opens_no_transaction_around_the_call(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """DV-19: it opens one transaction per seat itself, so none may surround the call.

    Seen from inside the grant call: a surrounding ``sm.begin()`` would be a begun transaction
    on a session this test cannot see, so ``sm.begin`` is spied on directly.
    """
    seen: list[object] = []
    begun: list[bool] = []
    real_begin = pg_sessionmaker.begin

    def spy_begin() -> object:
        begun.append(True)
        return real_begin()

    def spy(sm: object, *, now: datetime) -> int:
        seen.append(sm)
        assert begun == []  # no transaction was opened before the call
        return 7

    monkeypatch.setattr(pg_sessionmaker, "begin", spy_begin)
    monkeypatch.setattr(subscription_jobs, "grant_monthly_seat_allowances", spy)
    assert subscription_jobs.monthly_seat_allowance_job(pg_sessionmaker, now=DEC_1) == 7
    assert seen == [pg_sessionmaker]
    assert begun == []


def test_drift_check_runs_once_per_utc_day(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=seed_tier(pg_sessionmaker),
        payer_id=student,
        paymob_subscription_id=4321,
        paymob_amount_minor=10_000,
    )
    client = FakePaymobClient()
    # Paymob holds a different amount (repaired by a PUT); the last charge is a decline.
    client.subscriptions[4321] = remote_subscription(4321, amount_cents=12_345)
    client.last_transactions[4321] = charge(1, 10_000, success=False)
    sweeper = _sweeper(pg_sessionmaker, client, DEC_1)
    assert sweeper.sweep_unbounded_for_tests()["subscriptions.drift_check"] == 1
    calls = len(client.calls)
    assert sweeper.sweep_unbounded_for_tests()["subscriptions.drift_check"] == 0
    assert len(client.calls) == calls  # memo: no Paymob call the same day
    sweeper.now = lambda: DEC_1 + timedelta(days=1)
    assert sweeper.sweep_unbounded_for_tests()["subscriptions.drift_check"] == 0  # in sync now
    assert len(client.calls) > calls  # but it did check


def test_a_drift_pass_that_raises_is_retried_on_the_next_tick(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[datetime] = []

    def flaky(
        self: SubscriptionService,
        *,
        now: datetime,
        limit: int = 1,
        should_stop: Callable[[], bool] | None = None,
    ) -> int:
        attempts.append(now)
        if len(attempts) == 1:
            raise RuntimeError("paymob is down")
        return 2

    monkeypatch.setattr(SubscriptionService, "check_drift", flaky)
    sweeper = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1)
    assert sweeper.sweep_unbounded_for_tests()["subscriptions.drift_check"] is None
    assert sweeper.sweep_unbounded_for_tests()["subscriptions.drift_check"] == 2
    assert len(attempts) == 2


def test_drift_covers_every_row_each_day_whatever_the_count(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """I-1: 201 rows exceed the 200-row batch; ticks on one UTC day must still reach them all."""
    client = FakePaymobClient()
    tier = seed_tier(pg_sessionmaker)
    for n in range(201):
        user = seed_user(pg_sessionmaker, Role.student)
        pid = 7000 + n
        seed_subscription(
            pg_sessionmaker,
            user_id=user,
            tier_id=tier,
            payer_id=user,
            paymob_subscription_id=pid,
            paymob_amount_minor=10_000,
        )
        client.subscriptions[pid] = remote_subscription(pid)
        client.last_transactions[pid] = charge(pid, 10_000, success=False)
    sweeper = _sweeper(pg_sessionmaker, client, DEC_1)
    for minutes in (0, 1, 300, 1300):
        sweeper.now = lambda m=minutes: DEC_1 + timedelta(minutes=m)
        sweeper.sweep_unbounded_for_tests()

    def unchecked() -> int:
        with pg_sessionmaker() as session:
            return len(
                session.scalars(
                    select(Subscription.id).where(Subscription.drift_checked_at.is_(None))
                ).all()
            )

    assert unchecked() == 0
    calls = len(client.calls)
    sweeper.now = lambda: DEC_1 + timedelta(minutes=1400)
    sweeper.sweep_unbounded_for_tests()
    assert len(client.calls) == calls  # all checked today: nothing to read
    sweeper.now = lambda: DEC_1 + timedelta(days=1, minutes=1)
    sweeper.sweep_unbounded_for_tests()
    assert len(client.calls) > calls  # the next UTC day starts over


def test_an_expiring_teacher_plan_gets_no_new_month_of_seat_allowance(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Order proof: expiry runs before the monthly seat grant in the same pass."""
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        included_seats=3,
        seat_allowance_units=300,
    )
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=teacher,
        tier_id=tier,
        payer_id=teacher,
        status=SubscriptionStatus.past_due,
        grace_until=DEC_1 - timedelta(minutes=1),
        paymob_subscription_id=4321,
        paymob_amount_minor=10_000,
    )
    student = seed_user(pg_sessionmaker, Role.student)
    seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=student)
    results = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1).sweep_unbounded_for_tests()
    assert results["subscriptions.expire_overdue"] == 1
    assert results["seats.monthly_allowance"] == 0
    with pg_sessionmaker() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        assert sub.status is SubscriptionStatus.expired
    assert grants_of(pg_sessionmaker, student) == []


def test_a_seat_leaving_at_month_end_is_released_before_the_new_grant(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        included_seats=3,
        seat_allowance_units=300,
    )
    seed_subscription(pg_sessionmaker, user_id=teacher, tier_id=tier, payer_id=teacher)
    leaver = seed_user(pg_sessionmaker, Role.student)
    stayer = seed_user(pg_sessionmaker, Role.student)
    leaving = seed_seat(
        pg_sessionmaker,
        teacher_id=teacher,
        student_id=leaver,
        status=TeacherMemberStatus.leaving,
        leaves_at=DEC_1 - timedelta(minutes=1),
    )
    seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=stayer)
    results = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1).sweep_unbounded_for_tests()
    assert (results["seats.release_due"], results["seats.monthly_allowance"]) == (1, 1)
    with pg_sessionmaker() as session:
        member = session.get(TeacherMember, leaving)
        assert member is not None
        assert member.status is TeacherMemberStatus.removed
    assert grants_of(pg_sessionmaker, leaver) == []
    assert len(grants_of(pg_sessionmaker, stayer)) == 1


def test_unconfigured_paymob_still_expires_an_overdue_plan_and_stops_its_allowance(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-2: the local expiry runs without Paymob; the cancel waits for the retry set."""
    unconfigured = paymob_settings(secret_key=None, public_key=None, api_key=None)
    assert not unconfigured.checkout_configured
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        included_seats=3,
        seat_allowance_units=300,
    )
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=teacher,
        tier_id=tier,
        payer_id=teacher,
        status=SubscriptionStatus.past_due,
        grace_until=DEC_1 - timedelta(days=20),
        paymob_subscription_id=4321,
        paymob_amount_minor=10_000,
    )
    student = seed_user(pg_sessionmaker, Role.student)
    seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=student)
    sweeper = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1, with_subscriptions=False)
    sweeper.expiry = SubscriptionDeps(pg_sessionmaker, PaymobClient(unconfigured), unconfigured)
    results = sweeper.sweep_unbounded_for_tests()
    assert list(results)[-3:] == ["subscriptions.expire_overdue", *SEAT_JOBS]
    assert results["subscriptions.expire_overdue"] == 1
    assert results["seats.monthly_allowance"] == 0
    with pg_sessionmaker() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        assert sub.status is SubscriptionStatus.expired
        assert sub.paymob_cancelled_at is None  # left to the failed-cancel retry set
    assert grants_of(pg_sessionmaker, student) == []


def test_the_underlying_calls_happen_in_dv32_order(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service calls themselves are ordered, not only the result keys.

    A leaving seat is never granted (only ``active`` seats are), so the release-before-grant
    order is not observable in rows; the call sequence is what DV-32 fixes.
    """
    calls: list[str] = []

    def expire(
        self: SubscriptionService,
        *,
        now: datetime,
        limit: int = 1,
        should_stop: Callable[[], bool] | None = None,
    ) -> int:
        calls.append("expire_overdue")
        return 0

    def release(self: TeacherTeamService, *, now: datetime) -> int:
        calls.append("release_due")
        return 0

    def grant(sm: object, *, now: datetime) -> int:
        calls.append("monthly_allowance")
        return 0

    monkeypatch.setattr(SubscriptionService, "expire_overdue", expire)
    monkeypatch.setattr(TeacherTeamService, "release_due", release)
    monkeypatch.setattr(subscription_jobs, "grant_monthly_seat_allowances", grant)
    _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1).sweep_unbounded_for_tests()
    assert calls == ["expire_overdue", "release_due", "monthly_allowance"]


@pytest.fixture
def fresh_singletons() -> Iterator[None]:
    def clear() -> None:
        deps.get_sweeper.cache_clear()
        deps_billing.get_subscription_deps.cache_clear()
        deps_billing.get_paymob_client.cache_clear()

    clear()
    yield
    clear()


def _use_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(deps_billing, "get_settings", lambda: settings)


@pytest.mark.usefixtures("fresh_singletons")
def test_get_sweeper_without_paymob_still_enables_seat_allowances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unconfigured = Settings().model_copy(
        update={"paymob": paymob_settings(secret_key=None, public_key=None, api_key=None)}
    )
    assert not unconfigured.paymob.checkout_configured
    _use_settings(monkeypatch, unconfigured)
    sweeper = deps.get_sweeper()
    assert sweeper.subscriptions is None
    assert sweeper.expiry is not None
    assert sweeper.seat_allowances is True


@pytest.mark.usefixtures("fresh_singletons")
def test_get_sweeper_with_paymob_wires_the_subscription_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = Settings().model_copy(update={"paymob": paymob_settings()})
    assert configured.paymob.checkout_configured
    _use_settings(monkeypatch, configured)
    sweeper = deps.get_sweeper()
    assert isinstance(sweeper.subscriptions, SubscriptionDeps)
    assert sweeper.seat_allowances is True
