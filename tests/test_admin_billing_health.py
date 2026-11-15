"""Billing health (spec §8 area 5): sweeper runs, webhook error rate, failed charges.

Real Postgres (a throwaway ``create_all`` database). Renewal failures are seeded through Phase
05's own writer (``SubscriptionService.apply_renewal_webhook``), never a hand-built payload
(DV-23): the trigger lives at ``payload["body"]["trigger_type"]``, which is not where the plan
read it.
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.admin_health_repo import BILLING_JOB_NAMES, AdminHealthService
from lemely.db.billing_observability_repo import JobRunRecorder
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.billing import PaymentPurpose, PaymentStatus, PaymobEvent, PaymobEventKind
from lemely.db.models.billing_ops import PaymobWebhookFailure
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.subscription_repo import (
    TRIGGER_FAILED,
    TRIGGER_OVERDUE,
    TRIGGER_SUCCESS,
    SubscriptionService,
)
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.routers import admin_billing_health
from lemely.web.schemas_admin_billing_health import BillingHealthDTO, JobHealthDTO
from tests.admin_billing_db import (
    NOW,
    add_payment,
    add_plan_tier,
    add_subscription,
    add_user,
    billing_database,
    emptied_after,
)
from tests.subscription_fixtures import (
    FakePaymobClient,
    charge,
    paymob_settings,
    remote_subscription,
    subscription_webhook,
)
from tests.tutoring_app import app_with_routers

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

PID = 4321
FRONTEND_TYPES = Path(__file__).parents[1] / "web" / "src" / "lib" / "billingTypes.ts"


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


def _client(sm: sessionmaker[Session], admin_id: uuid.UUID) -> TestClient:
    """The whole app as ``admin_id``; the health service is bound to ``sm`` and ``NOW``."""
    app = app_with_routers(admin_billing_health.router)
    app.dependency_overrides[admin_billing_health.get_admin_health_service] = lambda: (
        AdminHealthService(sm, now=lambda: NOW)
    )
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin_id), role=Role.platform_admin.value
    )
    return TestClient(app)


def _event(sm: sessionmaker[Session], kind: PaymobEventKind, hours_ago: float) -> uuid.UUID:
    event_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            PaymobEvent(
                id=event_id,
                kind=kind,
                dedupe_key=str(event_id),
                payload={"obj": {}},
                created_at=NOW - timedelta(hours=hours_ago),
            )
        )
    return event_id


def _hmac_failures(sm: sessionmaker[Session], count: int, hours_ago: float = 1) -> None:
    with sm.begin() as session:
        for _ in range(count):
            session.add(
                PaymobWebhookFailure(
                    kind="transaction",
                    reason="hmac_mismatch",
                    received_at=NOW - timedelta(hours=hours_ago),
                )
            )


def _renewal_webhook(sm: sessionmaker[Session], trigger: str, hours_ago: float) -> None:
    """Deliver one subscription callback through Phase 05's writer, then date its stored event.

    No local subscription matches, so the event is stored unprocessed with the remote copy: the
    state a failure is in when the plan is not linked yet. Its ``created_at`` is moved into the
    test's clock (a server default would be the real time).
    """
    client = FakePaymobClient()
    client.subscriptions[PID] = remote_subscription(
        PID, updated_at=f"2026-11-04T{int(hours_ago):02d}:00:00"
    )
    client.last_transactions[PID] = charge(
        900 + int(hours_ago), 10_000, success=trigger == TRIGGER_SUCCESS
    )
    with sm.begin() as session:
        SubscriptionService(session, client, paymob_settings()).apply_renewal_webhook(
            subscription_webhook(trigger, PID), now=NOW
        )
    with sm.begin() as session:
        session.execute(
            sa.update(PaymobEvent)
            .where(
                PaymobEvent.kind == PaymobEventKind.subscription,
                PaymobEvent.dedupe_key.like(f"sub:{PID}:{trigger}:%"),
            )
            .values(created_at=NOW - timedelta(hours=hours_ago))
        )


def test_health_reports_jobs_webhooks_and_failed_charges(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    recorder = JobRunRecorder(sm)
    recorder.finish("billing.reconcile_pending", now=NOW, count=2, error=None)
    recorder.finish("usage.expire_grants", now=NOW, count=None, error=RuntimeError("boom"))
    for _ in range(3):
        _event(sm, PaymobEventKind.transaction, 1)
    _renewal_webhook(sm, TRIGGER_FAILED, 2)
    _renewal_webhook(sm, TRIGGER_OVERDUE, 30)  # outside the 24 h window
    _hmac_failures(sm, 1)
    student = add_user(sm, Role.student)
    add_payment(
        sm, payer=student, status=PaymentStatus.failed_mismatch, updated_at=NOW - timedelta(hours=1)
    )
    add_payment(
        sm,
        payer=student,
        purpose=PaymentPurpose.auto_topup,
        status=PaymentStatus.failed,
        updated_at=NOW - timedelta(hours=2),
    )
    add_payment(
        sm,
        payer=student,
        purpose=PaymentPurpose.extra_seats,
        status=PaymentStatus.failed,
        updated_at=NOW - timedelta(hours=3),
    )
    add_payment(
        sm,
        payer=student,
        purpose=PaymentPurpose.extra_seats,
        status=PaymentStatus.failed,
        updated_at=NOW - timedelta(hours=48),
    )
    add_subscription(sm, student, add_plan_tier(sm), status=SubscriptionStatus.past_due)

    resp = _client(sm, admin).get("/api/admin/billing/health", params={"hours": 24})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    jobs = {j["name"]: j for j in body["jobs"]}
    assert set(BILLING_JOB_NAMES) <= set(jobs)
    reconcile = jobs["billing.reconcile_pending"]
    assert (reconcile["lastOutcome"], reconcile["lastResultCount"], reconcile["neverRun"]) == (
        "ok",
        2,
        False,
    )
    expire = jobs["usage.expire_grants"]
    assert (expire["lastOutcome"], expire["consecutiveFailures"], expire["lastError"]) == (
        "failed",
        1,
        "RuntimeError",
    )
    assert jobs["usage.reconcile_balances"]["neverRun"] is True
    assert {
        k: body[k]
        for k in (
            "windowHours",
            "verifiedEvents",
            "hmacFailures",
            "webhookErrorRate",
            "mismatches",
            "renewalFailureEvents",
            "pastDueNow",
            "failedAutoTopups",
            "failedExtraSeatCharges",
        )
    } == {
        "windowHours": 24,
        "verifiedEvents": 4,  # three transactions and the in-window failure callback
        "hmacFailures": 1,
        "webhookErrorRate": 0.2,
        "mismatches": 1,
        "renewalFailureEvents": 1,
        "pastDueNow": 1,
        "failedAutoTopups": 1,
        "failedExtraSeatCharges": 1,
    }


def test_a_wider_window_counts_the_older_failures_and_past_due_is_not_windowed(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _renewal_webhook(sm, TRIGGER_FAILED, 2)
    _renewal_webhook(sm, TRIGGER_OVERDUE, 30)
    student = add_user(sm, Role.student)
    add_subscription(sm, student, add_plan_tier(sm), status=SubscriptionStatus.past_due)
    client = _client(sm, admin)

    wide = client.get("/api/admin/billing/health", params={"hours": 48}).json()
    narrow = client.get("/api/admin/billing/health", params={"hours": 1}).json()

    assert (wide["renewalFailureEvents"], wide["pastDueNow"]) == (2, 1)
    assert (narrow["renewalFailureEvents"], narrow["pastDueNow"]) == (0, 1)


def test_a_successful_renewal_is_not_a_renewal_failure(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _renewal_webhook(sm, TRIGGER_SUCCESS, 2)
    body = _client(sm, admin).get("/api/admin/billing/health").json()
    assert body["verifiedEvents"] == 1
    assert body["renewalFailureEvents"] == 0


def test_only_billing_jobs_are_listed(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    recorder = JobRunRecorder(sm)
    recorder.finish("announcements.publish_due", now=NOW, count=1, error=None)
    recorder.finish("deliver_tutoring_email", now=NOW, count=1, error=None)
    recorder.finish("subscriptions.expire_overdue", now=NOW, count=0, error=None)

    jobs = {
        j["name"]: j for j in _client(sm, admin).get("/api/admin/billing/health").json()["jobs"]
    }

    assert "announcements.publish_due" not in jobs
    assert "deliver_tutoring_email" not in jobs
    assert jobs["subscriptions.expire_overdue"]["neverRun"] is False
    assert jobs["usage.repair_signup_grants"]["neverRun"] is True


def test_a_first_run_that_never_finished_is_not_an_ok_run(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    JobRunRecorder(sm).start("billing.reconcile_pending", NOW - timedelta(days=3))

    jobs = {j["name"]: j for j in _client(sm, admin).get("/api/admin/billing/health").json()["jobs"]}

    job = jobs["billing.reconcile_pending"]
    assert (job["neverRun"], job["lastOutcome"], job["totalRuns"]) == (True, None, 0)
    assert job["lastStartedAt"] is not None


def test_the_job_list_is_the_billing_names_in_order(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    names = [j["name"] for j in _client(sm, admin).get("/api/admin/billing/health").json()["jobs"]]
    assert names == sorted(BILLING_JOB_NAMES)
    assert "usage.repair_signup_grants" in names
    assert "billing.prune_webhook_failures" in names


def test_error_rate_is_failures_over_failures_plus_verified_events(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _hmac_failures(sm, 3)
    for _ in range(7):
        _event(sm, PaymobEventKind.transaction, 1)
    for kind in (PaymobEventKind.token, PaymobEventKind.subscription):
        _event(sm, kind, 100)  # outside the window, so not counted

    body = _client(sm, admin).get("/api/admin/billing/health").json()

    assert (body["hmacFailures"], body["verifiedEvents"], body["webhookErrorRate"]) == (3, 7, 0.3)


def test_every_event_kind_counts_as_a_verified_event(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    for kind in PaymobEventKind:
        _event(sm, kind, 1)
    body = _client(sm, admin).get("/api/admin/billing/health").json()
    assert body["verifiedEvents"] == len(PaymobEventKind)


def test_the_rate_is_documented_as_failures_per_stored_event() -> None:
    """``paymob_events`` records no source, so inquiry results cannot be told from callbacks."""
    doc = " ".join((BillingHealthDTO.__doc__ or "").split())
    assert "HMAC failures per stored Paymob event" in doc
    assert "60 rows per minute per process" in doc


def test_a_reconcile_inquiry_event_counts_as_a_stored_event(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """Pins the documented meaning: any stored event, whatever its source, is in the rate."""
    _hmac_failures(sm, 1)
    _event(sm, PaymobEventKind.transaction, 1)  # stored the way an inquiry result is
    body = _client(sm, admin).get("/api/admin/billing/health").json()
    assert body["webhookErrorRate"] == 0.5


def test_no_traffic_means_no_error_rate(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    body = _client(sm, admin).get("/api/admin/billing/health").json()
    assert body["webhookErrorRate"] is None
    assert body["windowHours"] == 24
    assert all(j["neverRun"] for j in body["jobs"])


@pytest.mark.parametrize("hours", [0, -1, 721])
def test_the_window_is_one_to_720_hours(
    sm: sessionmaker[Session], admin: uuid.UUID, hours: int
) -> None:
    resp = _client(sm, admin).get("/api/admin/billing/health", params={"hours": hours})
    assert resp.status_code == 422


@pytest.mark.parametrize("hours", [1, 720])
def test_the_window_bounds_are_accepted(
    sm: sessionmaker[Session], admin: uuid.UUID, hours: int
) -> None:
    resp = _client(sm, admin).get("/api/admin/billing/health", params={"hours": hours})
    assert resp.status_code == 200


def test_health_is_read_only(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    _client(sm, admin).get("/api/admin/billing/health")
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(AdminAuditLog)) == 0


def _ts_keys(interface: str) -> set[str]:
    source = FRONTEND_TYPES.read_text()
    match = re.search(rf"export interface {interface} \{{(.*?)\n\}}", source, re.DOTALL)
    assert match, interface
    return set(re.findall(r"^\s{2}(\w+)\??:", match.group(1), re.MULTILINE))


def test_the_dto_keys_are_the_frontend_keys() -> None:
    assert set(BillingHealthDTO.model_fields) == _ts_keys("BillingHealth")
    assert set(JobHealthDTO.model_fields) == _ts_keys("SweeperJobHealth")
