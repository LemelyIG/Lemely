"""Subscription actions (spec §8 area 2): complimentary activation, extend, cancel, expiry."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
import structlog
from fastapi.testclient import TestClient

from lemely.db import admin_customer_repo
from lemely.db.admin_billing_repo import AdminConflictError, AuditAction, ReasonRequiredError
from lemely.db.admin_customer_repo import AdminCustomerService, expire_manual_subscriptions
from lemely.db.admin_repo import PlatformAdminService, SubscriptionConflictError
from lemely.db.models.billing import PlanTier, Subscription, SubscriptionPeriod
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.usage import UsageEntry, UsageGrant, UsageGrantBalance
from lemely.db.subscription_repo import SubscriptionService
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.deps_billing import get_billing_sessionmaker
from lemely.web.routers.billing import get_billing_clock
from lemely.web.usage import get_usage_meter
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_plan_tier,
    add_subscription,
    add_user,
    admin_client,
    audit_rows,
    billing_database,
    emptied_after,
)
from tests.paymob_fixtures import PAYMOB_SETTINGS
from tests.usage_helpers import enforcing_meter

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


def _activate(
    sm: sessionmaker[Session], admin: uuid.UUID, user: uuid.UUID, tier: uuid.UUID, days: int = 30
) -> dict[str, Any]:
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/customers/{user}/manual-activation",
        json={"planTierId": str(tier), "periodDays": days, "reason": "school pilot"},
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _service(
    sm: sessionmaker[Session], paymob: FakePaymobClient | None = None
) -> AdminCustomerService:
    return AdminCustomerService(sm, paymob or FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: NOW)


def _subscription(sm: sessionmaker[Session], sub: uuid.UUID) -> Subscription:
    with sm() as session:
        return session.get_one(Subscription, sub)


def _complimentary(
    sm: sessionmaker[Session], user: uuid.UUID, tier: uuid.UUID, *, end: datetime | None
) -> uuid.UUID:
    """A complimentary row seeded directly: no payer, no Paymob id, an optional period end."""
    sub = add_subscription(sm, user, tier, manual=True, end=end)
    with sm.begin() as session:
        session.get_one(Subscription, sub).payer_user_id = None
    return sub


# -- manual activation -------------------------------------------------------------


def test_manual_activation_creates_a_live_complimentary_plan(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm, allowance_units=1000)
    body = _activate(sm, admin, student, tier)
    [sub] = body["subscriptions"]
    assert (sub["status"], sub["isManuallyActivated"], sub["paymobSubscriptionId"]) == (
        "active",
        True,
        None,
    )
    # DV-16: complimentary means no payer.
    assert sub["payerUserId"] is None
    assert datetime.fromisoformat(sub["currentPeriodEnd"]) == NOW + timedelta(days=30)
    [allowance] = [g for g in body["grants"] if g["kind"] == "period_allowance"]
    assert (allowance["units"], allowance["visible"]) == (1000, False)
    assert datetime.fromisoformat(allowance["expiresAt"]) == NOW + timedelta(days=30)
    assert body["balance"]["allowanceAvailable"] == 1000
    [row] = audit_rows(sm, AuditAction.SUBSCRIPTION_MANUAL_ACTIVATION)
    assert row.target_id == uuid.UUID(sub["id"])
    assert row.after is not None
    assert row.after["allowance_grant_id"] == allowance["id"]
    with sm() as session:
        stored = session.get_one(Subscription, uuid.UUID(sub["id"]))
        assert stored.activation_note == "school pilot"
        assert stored.payer_user_id is None
        period = session.scalars(
            sa.select(SubscriptionPeriod).where(SubscriptionPeriod.subscription_id == stored.id)
        ).one()
        grant = session.get_one(UsageGrant, uuid.UUID(allowance["id"]))
        assert grant.subscription_period_id == period.id
        assert grant.idempotency_key == f"admin-activation:{stored.id}"


def test_a_zero_allowance_tier_issues_no_grant(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    body = _activate(sm, admin, student, add_plan_tier(sm, allowance_units=0))
    assert [g for g in body["grants"] if g["kind"] == "period_allowance"] == []
    [row] = audit_rows(sm, AuditAction.SUBSCRIPTION_MANUAL_ACTIVATION)
    assert row.after is not None
    assert row.after["allowance_grant_id"] is None


def test_the_user_cannot_manage_a_complimentary_plan(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """No payer, so the billing summary offers the user no card or cancel controls."""
    student = add_user(sm, Role.student)
    _activate(sm, admin, student, add_plan_tier(sm))
    app = create_app()
    app.dependency_overrides[get_billing_sessionmaker] = lambda: sm
    app.dependency_overrides[get_billing_clock] = lambda: lambda: NOW
    app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(sm)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(student), role=Role.student.value
    )
    resp = TestClient(app).get("/api/billing/summary")
    assert resp.status_code == 200, resp.text
    assert resp.json()["canManage"] is False


@pytest.mark.parametrize("other_payer_is_a_third_party", [False, True])
def test_a_second_live_plan_is_409(
    sm: sessionmaker[Session], admin: uuid.UUID, other_payer_is_a_third_party: bool
) -> None:
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm)
    live = add_subscription(sm, student, tier)
    if other_payer_is_a_third_party:
        with sm.begin() as session:
            session.get_one(Subscription, live).payer_user_id = add_user(sm, Role.parent)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/customers/{student}/manual-activation",
        json={"planTierId": str(tier), "periodDays": 30, "reason": "dup"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "live_subscription_exists"
    assert audit_rows(sm, AuditAction.SUBSCRIPTION_MANUAL_ACTIVATION) == []


@pytest.mark.parametrize("role", [Role.parent, Role.platform_admin, Role.teacher])
def test_a_student_tier_for_another_role_is_422(
    sm: sessionmaker[Session], admin: uuid.UUID, role: Role
) -> None:
    user = add_user(sm, role)
    tier = add_plan_tier(sm)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/customers/{user}/manual-activation",
        json={"planTierId": str(tier), "periodDays": 30, "reason": "wrong"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "audience_mismatch"
    assert audit_rows(sm, AuditAction.SUBSCRIPTION_MANUAL_ACTIVATION) == []


def test_a_teacher_tier_for_a_student_is_422(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm, code="teacher_monthly", audience="teacher", included_seats=5)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/customers/{student}/manual-activation",
        json={"planTierId": str(tier), "periodDays": 30, "reason": "wrong"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "audience_mismatch"


def test_a_teacher_gets_a_teacher_tier(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    teacher = add_user(sm, Role.teacher)
    tier = add_plan_tier(sm, code="teacher_monthly", audience="teacher", included_seats=5)
    body = _activate(sm, admin, teacher, tier)
    assert body["subscriptions"][0]["status"] == "active"


@pytest.mark.parametrize("which", ["inactive", "free"])
def test_only_a_sellable_tier_can_be_activated(
    sm: sessionmaker[Session], admin: uuid.UUID, which: str
) -> None:
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm, price_minor=0 if which == "free" else 20000)
    if which == "inactive":
        with sm.begin() as session:
            session.get_one(PlanTier, tier).is_active = False
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/customers/{student}/manual-activation",
        json={"planTierId": str(tier), "periodDays": 30, "reason": "pilot"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "plan_not_activatable"
    assert audit_rows(sm, AuditAction.SUBSCRIPTION_MANUAL_ACTIVATION) == []


def test_unknown_customer_tier_and_blank_reason_change_nothing(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm)
    client = admin_client(sm, admin)
    base = "/api/admin/billing/customers/{}/manual-activation"
    missing_user = client.post(
        base.format(uuid.uuid4()),
        json={"planTierId": str(tier), "periodDays": 30, "reason": "x y z"},
    )
    missing_tier = client.post(
        base.format(student),
        json={"planTierId": str(uuid.uuid4()), "periodDays": 30, "reason": "x y z"},
    )
    blank = client.post(
        base.format(student), json={"planTierId": str(tier), "periodDays": 30, "reason": "   "}
    )
    assert (missing_user.status_code, missing_tier.status_code, blank.status_code) == (
        404,
        404,
        422,
    )
    with pytest.raises(ReasonRequiredError):
        _service(sm).manual_activation(
            student, plan_tier_id=tier, period_days=30, admin_user_id=admin, reason="  "
        )
    assert audit_rows(sm, AuditAction.SUBSCRIPTION_MANUAL_ACTIVATION) == []
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Subscription)) == 0


def test_activation_waits_for_the_user_row_lock_then_sees_the_other_plan(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """The per-user row lock (the one ``decide_activation`` takes) serialises activations.

    Complimentary rows have no payer, so the partial unique index does not cover them: this
    lock is the only thing keeping one live plan per user. A side transaction holds it and
    commits a live plan; the activation must wait, then refuse.
    """
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm)
    outcome: list[BaseException | None] = []

    def attempt() -> None:
        try:
            _service(sm).manual_activation(
                student, plan_tier_id=tier, period_days=30, admin_user_id=admin, reason="race"
            )
            outcome.append(None)
        except BaseException as exc:
            outcome.append(exc)

    with sm.begin() as holder:
        holder.execute(
            sa.text("SELECT id FROM users WHERE id = :u FOR NO KEY UPDATE"), {"u": student}
        )
        worker = threading.Thread(target=attempt)
        worker.start()
        worker.join(1.0)
        assert worker.is_alive(), "the activation did not wait for the user-row lock"
        holder.add(
            Subscription(
                user_id=student,
                plan_tier_id=tier,
                status=SubscriptionStatus.active,
                is_manually_activated=True,
                current_period_start=NOW,
                current_period_end=NOW + timedelta(days=3),
            )
        )
    worker.join(10.0)
    assert not worker.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], AdminConflictError)
    assert outcome[0].code == "live_subscription_exists"


def test_a_manual_and_a_queue_activation_for_one_user_make_one_live_plan(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm)
    queued = add_subscription(sm, student, tier, status=SubscriptionStatus.inactive, end=None)
    barrier = threading.Barrier(2)
    results: dict[str, BaseException | None] = {}

    def manual() -> None:
        barrier.wait()
        try:
            _service(sm).manual_activation(
                student, plan_tier_id=tier, period_days=30, admin_user_id=admin, reason="manual"
            )
            results["manual"] = None
        except BaseException as exc:
            results["manual"] = exc

    def queue() -> None:
        barrier.wait()
        try:
            PlatformAdminService(sm).decide_activation(
                queued, activate=True, note="queue", admin_user_id=admin
            )
            results["queue"] = None
        except BaseException as exc:
            results["queue"] = exc

    threads = [threading.Thread(target=manual), threading.Thread(target=queue)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20.0)
    failures = [r for r in results.values() if r is not None]
    assert len(results) == 2
    assert len(failures) == 1
    assert isinstance(failures[0], AdminConflictError | SubscriptionConflictError)
    with sm() as session:
        live = session.scalar(
            sa.select(sa.func.count())
            .select_from(Subscription)
            .where(
                Subscription.user_id == student, Subscription.status == SubscriptionStatus.active
            )
        )
    assert live == 1


# -- extend ------------------------------------------------------------------------


def test_extend_moves_the_period_end_and_the_allowance_expiry(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    body = _activate(sm, admin, student, add_plan_tier(sm), days=5)
    sub = uuid.UUID(body["subscriptions"][0]["id"])
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{sub}/extend", json={"days": 10, "reason": "exam season"}
    )
    assert resp.status_code == 200, resp.text
    assert _subscription(sm, sub).current_period_end == NOW + timedelta(days=15)
    with sm() as session:
        period = session.scalars(
            sa.select(SubscriptionPeriod).where(SubscriptionPeriod.subscription_id == sub)
        ).one()
        assert period.period_end == NOW + timedelta(days=15)
        grant = session.scalars(
            sa.select(UsageGrant).where(UsageGrant.subscription_period_id == period.id)
        ).one()
        assert grant.expires_at == NOW + timedelta(days=15)
    [row] = audit_rows(sm, AuditAction.SUBSCRIPTION_EXTEND)
    assert row.before is not None
    assert datetime.fromisoformat(str(row.before["current_period_end"])) == NOW + timedelta(days=5)
    assert row.after is not None
    assert row.after["days"] == 10
    assert row.after["extended_grant_ids"] == [str(grant.id)]


def test_extending_a_plan_without_an_allowance_grant_still_moves_the_period(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    sub = _complimentary(sm, student, add_plan_tier(sm), end=NOW + timedelta(days=5))
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{sub}/extend", json={"days": 10, "reason": "exam season"}
    )
    assert resp.status_code == 200, resp.text
    assert _subscription(sm, sub).current_period_end == NOW + timedelta(days=15)


def test_extending_a_paymob_billed_plan_is_409(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    sub = add_subscription(sm, student, add_plan_tier(sm), paymob_subscription_id=7001)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{sub}/extend", json={"days": 10, "reason": "no way"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "paymob_billed"
    assert audit_rows(sm, AuditAction.SUBSCRIPTION_EXTEND) == []


@pytest.mark.parametrize(
    ("end", "status", "code"),
    [
        (None, SubscriptionStatus.active, "open_ended"),
        (NOW + timedelta(days=5), SubscriptionStatus.cancelled, "not_extendable"),
    ],
)
def test_extend_refuses_what_it_cannot_extend(
    sm: sessionmaker[Session],
    admin: uuid.UUID,
    end: datetime | None,
    status: SubscriptionStatus,
    code: str,
) -> None:
    student = add_user(sm, Role.student)
    sub = _complimentary(sm, student, add_plan_tier(sm), end=end)
    with sm.begin() as session:
        session.get_one(Subscription, sub).status = status
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{sub}/extend", json={"days": 10, "reason": "try it"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == code
    assert audit_rows(sm, AuditAction.SUBSCRIPTION_EXTEND) == []


def test_extend_of_an_unknown_subscription_is_404(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{uuid.uuid4()}/extend",
        json={"days": 1, "reason": "gone"},
    )
    assert resp.status_code == 404


# -- cancel (complimentary) --------------------------------------------------------


def test_cancel_at_period_end_then_the_sweeper_ends_complimentary_plans(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    end = NOW + timedelta(days=3)
    cancelled = _complimentary(sm, add_user(sm, Role.student), tier, end=end)
    lapsing = _complimentary(sm, add_user(sm, Role.student), tier, end=end)
    legacy = _complimentary(sm, add_user(sm, Role.student), tier, end=None)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{cancelled}/cancel",
        json={"when": "period_end", "reason": "pilot over"},
    )
    assert resp.status_code == 200, resp.text
    assert _subscription(sm, cancelled).cancel_at_period_end is True
    assert _subscription(sm, cancelled).status is SubscriptionStatus.active

    assert expire_manual_subscriptions(sm, now=end - timedelta(seconds=1)) == 0
    assert expire_manual_subscriptions(sm, now=end) == 2
    assert _subscription(sm, cancelled).status is SubscriptionStatus.cancelled
    assert _subscription(sm, lapsing).status is SubscriptionStatus.expired
    assert _subscription(sm, legacy).status is SubscriptionStatus.active
    [row] = audit_rows(sm, AuditAction.SUBSCRIPTION_CANCEL)
    assert row.after is not None
    assert row.after["when"] == "period_end"


def test_cancel_now_ends_access_and_the_allowance_at_the_next_sweep(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """UD-2: the unspent allowance stops being usable and is taken by the next expiry sweep."""
    student = add_user(sm, Role.student)
    body = _activate(sm, admin, student, add_plan_tier(sm, allowance_units=1000))
    sub = uuid.UUID(body["subscriptions"][0]["id"])
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=student, units=-300, reason="spent", idempotency_key="spend", now=NOW
        )
    later = NOW + timedelta(hours=1)  # a grant never ends before it starts, so cancel after it
    detail = AdminCustomerService(
        sm, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: later
    ).cancel_subscription(sub, when="now", admin_user_id=admin, reason="fraud")
    row = _subscription(sm, sub)
    assert (row.status, row.current_period_end, row.cancel_at_period_end) == (
        SubscriptionStatus.cancelled,
        later,
        False,
    )
    assert detail.balance.allowance_available == 0
    with sm() as session:
        [grant] = session.scalars(sa.select(UsageGrant)).all()
        assert grant.expires_at == later
        assert session.get_one(UsageGrantBalance, grant.id).remaining == 700  # not clawed back yet
    with sm.begin() as session:
        assert UsageLedger(session).expire_grants(now=later + timedelta(seconds=1)) == 1
    with sm() as session:
        assert session.get_one(UsageGrantBalance, grant.id).remaining == 0
        spent = session.scalar(
            sa.select(sa.func.sum(UsageEntry.units)).where(UsageEntry.grant_id == grant.id)
        )
        assert spent == 0  # issue 1000, spend -300, expire -700
    [audit] = audit_rows(sm, AuditAction.SUBSCRIPTION_CANCEL)
    assert audit.after is not None
    assert audit.after["when"] == "now"
    assert audit.after["ended_grant_ids"] == [str(grant.id)]
    assert audit.after["unspent_allowance_units"] == 700
    assert audit.after["allowance_ends"] == "next_expiry_sweep"


def test_cancel_now_of_a_plan_with_no_grant_just_ends_it(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    sub = _complimentary(
        sm, add_user(sm, Role.student), add_plan_tier(sm), end=NOW + timedelta(days=3)
    )
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{sub}/cancel", json={"when": "now", "reason": "done"}
    )
    assert resp.status_code == 200, resp.text
    assert _subscription(sm, sub).status is SubscriptionStatus.cancelled
    [audit] = audit_rows(sm, AuditAction.SUBSCRIPTION_CANCEL)
    assert audit.after is not None
    assert audit.after["ended_grant_ids"] == []


def test_cancelling_a_cancelled_plan_is_409(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    sub = add_subscription(sm, student, add_plan_tier(sm), status=SubscriptionStatus.cancelled)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{sub}/cancel", json={"when": "now", "reason": "again"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "not_live"
    assert audit_rows(sm, AuditAction.SUBSCRIPTION_CANCEL) == []


def test_cancel_of_an_unknown_subscription_is_404(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{uuid.uuid4()}/cancel",
        json={"when": "now", "reason": "gone"},
    )
    assert resp.status_code == 404


# -- the expiry job ----------------------------------------------------------------


def _lapsed(sm: sessionmaker[Session], count: int) -> list[uuid.UUID]:
    tier = add_plan_tier(sm)
    return [
        _complimentary(sm, add_user(sm, Role.student), tier, end=NOW - timedelta(days=i + 1))
        for i in range(count)
    ]


def test_the_job_is_bounded_and_takes_the_oldest_period_end_first(
    sm: sessionmaker[Session],
) -> None:
    newest, middle, oldest = _lapsed(sm, 3)
    assert expire_manual_subscriptions(sm, now=NOW, limit=1) == 1
    assert _subscription(sm, oldest).status is SubscriptionStatus.expired
    assert _subscription(sm, middle).status is SubscriptionStatus.active
    assert _subscription(sm, newest).status is SubscriptionStatus.active
    assert expire_manual_subscriptions(sm, now=NOW, limit=10) == 2


def test_the_job_leaves_paymob_billed_payer_and_non_manual_rows_alone(
    sm: sessionmaker[Session],
) -> None:
    tier = add_plan_tier(sm)
    past = NOW - timedelta(days=1)
    billed = add_subscription(
        sm, add_user(sm, Role.student), tier, manual=True, end=past, paymob_subscription_id=9
    )
    with sm.begin() as session:
        session.get_one(Subscription, billed).payer_user_id = None
    paid_by = add_subscription(sm, add_user(sm, Role.student), tier, manual=True, end=past)
    not_manual = add_subscription(sm, add_user(sm, Role.student), tier, manual=False, end=past)
    with sm.begin() as session:
        session.get_one(Subscription, not_manual).payer_user_id = None
    assert expire_manual_subscriptions(sm, now=NOW) == 0
    for sub in (billed, paid_by, not_manual):
        assert _subscription(sm, sub).status is SubscriptionStatus.active


def test_a_row_another_transaction_holds_is_skipped_not_waited_for(
    sm: sessionmaker[Session],
) -> None:
    held, free = _lapsed(sm, 2)
    result: list[int] = []
    with sm.begin() as holder:
        holder.execute(sa.select(Subscription.id).where(Subscription.id == held).with_for_update())
        worker = threading.Thread(
            target=lambda: result.append(expire_manual_subscriptions(sm, now=NOW))
        )
        worker.start()
        worker.join(5.0)
        blocked = worker.is_alive()
    worker.join(10.0)
    assert not blocked, "the job waited for a row another transaction holds"
    assert result == [1]
    assert _subscription(sm, held).status is SubscriptionStatus.active
    assert _subscription(sm, free).status is SubscriptionStatus.expired


def test_one_failing_row_does_not_stop_the_others_and_alerts(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    newest, _, oldest = _lapsed(sm, 3)
    real = admin_customer_repo._expire_manual_row

    def flaky(factory: sessionmaker[Session], sub_id: uuid.UUID, now: datetime) -> bool:
        if sub_id == oldest:
            raise RuntimeError("secret detail that must not be logged")
        return real(factory, sub_id, now)

    monkeypatch.setattr(admin_customer_repo, "_expire_manual_row", flaky)
    with structlog.testing.capture_logs() as logs:
        assert expire_manual_subscriptions(sm, now=NOW) == 2
    assert _subscription(sm, oldest).status is SubscriptionStatus.active
    assert _subscription(sm, newest).status is SubscriptionStatus.expired
    [alert] = [e for e in logs if e["event"] == "admin_manual_expiry_failed"]
    assert alert["alert"] is True
    assert alert["subscription_id"] == str(oldest)
    assert alert["error_type"] == "RuntimeError"
    assert "secret detail" not in str(logs)


# -- Phase 05 sweeps leave complimentary rows alone (R15) --------------------------


def test_the_paymob_sweeps_never_touch_a_complimentary_row(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    sub = _complimentary(sm, student, add_plan_tier(sm), end=NOW - timedelta(days=1))
    with sm.begin() as session:
        row = session.get_one(Subscription, sub)
        row.status = SubscriptionStatus.past_due
        row.grace_until = NOW - timedelta(hours=1)
    paymob = FakePaymobClient()
    with sm() as session:
        service = SubscriptionService(session, paymob, PAYMOB_SETTINGS)
        service.expire_overdue(now=NOW)
    with sm() as session:
        SubscriptionService(session, paymob, PAYMOB_SETTINGS).apply_period_end_changes(now=NOW)
    with sm() as session:
        SubscriptionService(session, paymob, PAYMOB_SETTINGS).check_drift(now=NOW)
    assert _subscription(sm, sub).status is SubscriptionStatus.past_due
    assert paymob.calls == []
