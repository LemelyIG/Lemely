"""Payments list, problem queue and manual reconcile (spec §8 area 3).

Paymob is never reached: every call goes to ``FakePaymobClient`` (scripted ``transaction_result``,
recorded calls). Each guard below was proved red by mutating the service (see the task report).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

import lemely.db.admin_payments_repo as payments_repo
from lemely.db.admin_billing_repo import AuditAction
from lemely.db.admin_payments_repo import AdminPaymentsService
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PaymobEvent,
    PaymobEventKind,
)
from lemely.db.models.billing_ops import (
    PaymentRefund,
    PaymobWebhookFailure,
    RefundKind,
    RefundStatus,
)
from lemely.db.models.enums import Role
from lemely.io.paymob.client import PaymobError
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.routers import admin_billing_payments
from lemely.web.routers.admin_billing_payments import get_admin_payments_service
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_payment,
    add_user,
    audit_count,
    audit_rows,
    billing_database,
    emptied_after,
    grant,
    service_overrides,
)
from tests.paymob_fixtures import PAYMOB_SETTINGS
from tests.tutoring_app import app_with_routers

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

BASE = "/api/admin/billing"


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


def _service(sm: sessionmaker[Session], paymob: FakePaymobClient) -> AdminPaymentsService:
    return AdminPaymentsService(sm, paymob, PAYMOB_SETTINGS, now=lambda: NOW)


def _client(
    sm: sessionmaker[Session], admin: uuid.UUID, paymob: FakePaymobClient | None = None
) -> TestClient:
    fake = paymob or FakePaymobClient()
    app = app_with_routers(admin_billing_payments.router)
    app.dependency_overrides.update(service_overrides(sm, fake))
    app.dependency_overrides[get_admin_payments_service] = lambda: _service(sm, fake)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin), role=Role.platform_admin.value
    )
    return TestClient(app)


def _add_refund(
    sm: sessionmaker[Session],
    payment: uuid.UUID,
    admin: uuid.UUID,
    *,
    status: RefundStatus,
    amount: int,
    age: timedelta,
    kind: RefundKind = RefundKind.refund,
) -> uuid.UUID:
    rid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            PaymentRefund(
                id=rid,
                payment_id=payment,
                admin_user_id=admin,
                kind=kind,
                status=status,
                amount_minor=amount,
                reason="seeded",
                created_at=NOW - age,
                updated_at=NOW - age,
            )
        )
    return rid


def _refund_status(sm: sessionmaker[Session], refund: uuid.UUID) -> RefundStatus:
    with sm() as session:
        row = session.get(PaymentRefund, refund)
        assert row is not None
        return row.status


def _payment_status(sm: sessionmaker[Session], payment: uuid.UUID) -> PaymentStatus:
    with sm() as session:
        row = session.get(Payment, payment)
        assert row is not None
        return row.status


def _inquiries(paymob: FakePaymobClient) -> list[dict[str, Any]]:
    return [kw for name, kw in paymob.calls if name == "inquire_by_transaction"]


def _post_reconcile(client: TestClient, payment: uuid.UUID, reason: str = "check it") -> Any:
    return client.post(f"{BASE}/payments/{payment}/reconcile", json={"reason": reason})


# -- the list ----------------------------------------------------------------------------


def test_the_list_filters_and_pages_newest_first(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student, other = add_user(sm, Role.student), add_user(sm, Role.student)
    ids = [add_payment(sm, payer=student, created_at=NOW - timedelta(minutes=m)) for m in (1, 2, 3)]
    add_payment(
        sm, payer=student, status=PaymentStatus.failed, created_at=NOW - timedelta(minutes=4)
    )
    add_payment(sm, payer=other, created_at=NOW - timedelta(minutes=5))
    client = _client(sm, admin)
    params: dict[str, Any] = {"status": "paid", "userId": str(student), "limit": 2}

    page1 = client.get(f"{BASE}/payments", params=params).json()
    page2 = client.get(f"{BASE}/payments", params={**params, "cursor": page1["nextCursor"]}).json()

    assert [p["id"] for p in page1["items"]] == [str(ids[0]), str(ids[1])]
    assert [p["id"] for p in page2["items"]] == [str(ids[2])]
    assert page2["nextCursor"] is None
    assert client.get(f"{BASE}/payments", params={"purpose": "auto_topup"}).json()["items"] == []


def test_a_user_filter_matches_the_beneficiary_too(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    payer, beneficiary = add_user(sm, Role.teacher), add_user(sm, Role.student)
    payment = add_payment(sm, payer=payer, beneficiary=beneficiary)
    body = _client(sm, admin).get(f"{BASE}/payments", params={"userId": str(beneficiary)}).json()
    assert [p["id"] for p in body["items"]] == [str(payment)]


def test_pages_of_fifty_have_no_duplicate_no_gap_and_survive_an_insert(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """Three payments share each timestamp, so a page edge falls inside a tie."""
    student = add_user(sm, Role.student)
    seeded = [
        add_payment(sm, payer=student, created_at=NOW - timedelta(minutes=1 + n // 3))
        for n in range(120)
    ]
    client = _client(sm, admin)

    first = client.get(f"{BASE}/payments", params={"limit": 50}).json()
    newer = add_payment(sm, payer=student, created_at=NOW)  # arrives between the pages
    second = client.get(
        f"{BASE}/payments", params={"limit": 50, "cursor": first["nextCursor"]}
    ).json()
    third = client.get(
        f"{BASE}/payments", params={"limit": 50, "cursor": second["nextCursor"]}
    ).json()

    pages = [first, second, third]
    assert [len(p["items"]) for p in pages] == [50, 50, 20]
    assert third["nextCursor"] is None
    seen = [p["id"] for page in pages for p in page["items"]]
    assert len(seen) == len(set(seen)) == 120
    assert set(seen) == {str(i) for i in seeded}
    assert str(newer) not in seen


def test_from_and_to_bound_the_list_and_must_carry_a_time_zone(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    old = add_payment(sm, payer=student, created_at=NOW - timedelta(days=3))
    recent = add_payment(sm, payer=student, created_at=NOW - timedelta(hours=1))
    client = _client(sm, admin)

    inside = client.get(
        f"{BASE}/payments", params={"from": (NOW - timedelta(days=1)).isoformat()}
    ).json()
    before = client.get(
        f"{BASE}/payments", params={"to": (NOW - timedelta(days=1)).isoformat()}
    ).json()
    naive = client.get(f"{BASE}/payments", params={"from": "2026-11-01T00:00:00"})
    naive_to = client.get(f"{BASE}/payments", params={"to": "2026-11-01T00:00:00"})

    assert [p["id"] for p in inside["items"]] == [str(recent)]
    assert [p["id"] for p in before["items"]] == [str(old)]
    for resp in (naive, naive_to):
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "naive_datetime"


def test_a_tampered_cursor_and_an_out_of_range_limit_are_422(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = _client(sm, admin)
    bad = client.get(f"{BASE}/payments", params={"cursor": "not-a-cursor"})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "bad_cursor"
    assert client.get(f"{BASE}/payments", params={"limit": 0}).status_code == 422
    assert client.get(f"{BASE}/payments", params={"limit": 201}).status_code == 422
    assert client.get(f"{BASE}/payments", params={"limit": 200}).status_code == 200


# -- the problem queue -------------------------------------------------------------------


def _queue(sm: sessionmaker[Session], admin: uuid.UUID) -> dict[str, Any]:
    resp = _client(sm, admin).get(f"{BASE}/problems")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def test_the_problem_queue_lists_each_kind_of_problem_once(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    mismatch = add_payment(
        sm, payer=student, status=PaymentStatus.failed_mismatch, paymob_txn_id=11
    )
    stale = add_payment(
        sm, payer=student, status=PaymentStatus.pending, created_at=NOW - timedelta(hours=2)
    )
    add_payment(
        sm, payer=student, status=PaymentStatus.pending, created_at=NOW - timedelta(minutes=30)
    )
    missing = add_payment(sm, payer=student, paid_at=NOW - timedelta(hours=1), paymob_txn_id=12)
    heard = add_payment(sm, payer=student, paid_at=NOW - timedelta(hours=1), paymob_txn_id=13)
    add_payment(
        sm,
        payer=student,
        purpose=PaymentPurpose.subscription_renewal,
        paid_at=NOW - timedelta(hours=1),
        paymob_txn_id=14,
    )
    add_payment(sm, payer=student, paid_at=NOW - timedelta(minutes=5), paymob_txn_id=15)
    with sm.begin() as session:
        session.get(Payment, heard).callback_received_at = NOW - timedelta(hours=1)  # type: ignore[union-attr]
    stuck = _add_refund(
        sm, heard, admin, status=RefundStatus.unknown, amount=100, age=timedelta(minutes=20)
    )
    _add_refund(sm, heard, admin, status=RefundStatus.unknown, amount=50, age=timedelta(minutes=2))
    with sm.begin() as session:
        session.add(
            PaymobWebhookFailure(
                kind="transaction",
                reason="hmac_mismatch",
                remote_addr="203.0.113.9",
                received_at=NOW - timedelta(hours=3),
            )
        )

    body = _queue(sm, admin)

    assert [p["id"] for p in body["mismatches"]] == [str(mismatch)]
    assert [p["id"] for p in body["stalePending"]] == [str(stale)]
    assert [p["id"] for p in body["missingCallbacks"]] == [str(missing)]
    assert [(f["kind"], f["reason"], f["remoteAddr"]) for f in body["hmacFailures"]] == [
        ("transaction", "hmac_mismatch", "203.0.113.9")
    ]
    assert body["hmacFailures24h"] == 1
    [refund] = body["refundsNeedingAttention"]
    assert (refund["id"], refund["paymentId"], refund["currency"]) == (
        str(stuck),
        str(heard),
        "EGP",
    )


def test_a_paid_payment_stamped_by_a_callback_is_not_a_missing_callback(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    heard = add_payment(sm, payer=student, paid_at=NOW - timedelta(hours=1), paymob_txn_id=21)
    unheard = add_payment(sm, payer=student, paid_at=NOW - timedelta(hours=1), paymob_txn_id=22)
    with sm.begin() as session:
        session.get(Payment, heard).callback_received_at = NOW - timedelta(minutes=50)  # type: ignore[union-attr]

    assert [p["id"] for p in _queue(sm, admin)["missingCallbacks"]] == [str(unheard)]


def test_an_open_payment_whose_callback_was_refused_for_its_integration_is_listed(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """The refusal still stamps ``callback_received_at`` (T2 M6), so the stamp cannot hide it."""
    student = add_user(sm, Role.student)
    refused = add_payment(
        sm, payer=student, status=PaymentStatus.pending, paymob_order_id=4242, paid_at=None
    )
    clean = add_payment(
        sm, payer=student, status=PaymentStatus.pending, paymob_order_id=4343, paid_at=None
    )
    with sm.begin() as session:
        for pid in (refused, clean):
            session.get(Payment, pid).callback_received_at = NOW - timedelta(minutes=1)  # type: ignore[union-attr]
        session.add(
            PaymobEvent(
                kind=PaymobEventKind.transaction,
                dedupe_key="rejected_integration:9001",
                payload={"order": {"id": 4242, "merchant_order_id": str(refused)}},
                processed_at=NOW,
            )
        )

    body = _queue(sm, admin)

    assert [p["id"] for p in body["missingCallbacks"]] == [str(refused)]
    assert body["stalePending"] == []  # created five minutes ago, so not stale as well


def test_the_webhook_failure_list_is_seven_days_newest_first_and_bounded_but_the_count_is_exact(
    sm: sessionmaker[Session], admin: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(payments_repo, "_QUEUE_LIMIT", 2)
    with sm.begin() as session:
        for hours in (30, 1, 2, 3, 24 * 8):
            session.add(
                PaymobWebhookFailure(
                    kind="token",
                    reason=f"r{hours}",
                    remote_addr=None,
                    received_at=NOW - timedelta(hours=hours),
                )
            )

    body = _queue(sm, admin)

    assert [f["reason"] for f in body["hmacFailures"]] == ["r1", "r2"]  # newest first, bounded
    assert body["hmacFailures24h"] == 3  # 1h, 2h, 3h: exact although the list holds two


def test_a_stale_requested_refund_is_listed_but_a_settled_one_is_not(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, paymob_txn_id=31)
    old_requested = _add_refund(
        sm, payment, admin, status=RefundStatus.requested, amount=100, age=timedelta(minutes=30)
    )
    _add_refund(sm, payment, admin, status=RefundStatus.failed, amount=100, age=timedelta(hours=3))
    _add_refund(
        sm, payment, admin, status=RefundStatus.requested, amount=100, age=timedelta(seconds=30)
    )

    ids = [r["id"] for r in _queue(sm, admin)["refundsNeedingAttention"]]

    assert ids == [str(old_requested)]


# -- reconcile ---------------------------------------------------------------------------


def test_reconcile_runs_the_phase_02_inquiry_for_one_payment_and_is_audited(
    sm: sessionmaker[Session], admin: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lemely.db.billing_repo import BillingService

    student = add_user(sm, Role.student)
    payment = add_payment(
        sm, payer=student, status=PaymentStatus.pending, created_at=NOW - timedelta(hours=2)
    )
    seen: list[uuid.UUID] = []

    def settle(self: BillingService, payment_id: uuid.UUID, *, now: datetime) -> PaymentStatus:
        seen.append(payment_id)
        row = self._session.get(Payment, payment_id)
        assert row is not None
        row.status = PaymentStatus.paid
        return row.status

    monkeypatch.setattr(BillingService, "reconcile_payment_now", settle)

    resp = _post_reconcile(_client(sm, admin), payment, "customer says paid")

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paid"
    assert seen == [payment]
    [row] = audit_rows(sm, AuditAction.PAYMENT_RECONCILE)
    assert (row.before["status"], row.after["status"]) == ("pending", "paid")
    assert row.reason == "customer says paid"
    assert row.target_id == payment


def test_every_reconcile_call_writes_one_audit_row(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student)  # settled: reconcile changes nothing
    client = _client(sm, admin)

    assert _post_reconcile(client, payment).status_code == 200
    assert _post_reconcile(client, payment).status_code == 200

    rows = audit_rows(sm, AuditAction.PAYMENT_RECONCILE)
    assert len(rows) == 2
    assert all(r.before["status"] == r.after["status"] == "paid" for r in rows)


def test_reconcile_of_an_unknown_payment_is_404_with_no_audit_and_a_short_reason_is_422(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = _client(sm, admin)
    missing = _post_reconcile(client, uuid.uuid4(), "who is this")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "payment_not_found"
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student)
    assert _post_reconcile(client, payment, "x").status_code == 422
    assert audit_count(sm) == 0


def test_a_payment_another_transaction_holds_is_409_not_500_and_leaves_no_audit(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(
        sm, payer=student, status=PaymentStatus.pending, created_at=NOW - timedelta(hours=2)
    )
    paymob = FakePaymobClient()
    with sm.begin() as holder:  # a sweeper pass or a callback holding the row
        holder.execute(sa.select(Payment).where(Payment.id == payment).with_for_update())
        resp = _post_reconcile(_client(sm, admin, paymob), payment)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "reconcile_in_progress"
    assert audit_rows(sm, AuditAction.PAYMENT_RECONCILE) == []
    assert _inquiries(paymob) == []
    # the row is free again afterwards, so the retry is not blocked
    assert _post_reconcile(_client(sm, admin, paymob), payment).status_code == 200


# -- settling refunds by inquiry ---------------------------------------------------------


def test_reconcile_settles_an_unknown_refund_visible_in_the_inquiry_and_claws_back_once(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(
        sm, payer=student, amount_minor=10000, paymob_order_id=777001, paymob_txn_id=888001
    )
    grant(sm, student, units=500, payment_id=payment)
    refund = _add_refund(
        sm, payment, admin, status=RefundStatus.unknown, amount=10000, age=timedelta(minutes=5)
    )
    paymob = FakePaymobClient()
    paymob.transaction_result = {"id": 888001, "refunded_amount_cents": 10000}
    client = _client(sm, admin, paymob)

    resp = _post_reconcile(client, payment, "check refund")
    again = _post_reconcile(client, payment, "check refund again")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "refunded"
    assert [r["status"] for r in body["refunds"]] == ["succeeded"]
    assert body["refunds"][0]["clawedBackUnits"] == 500
    assert again.json()["refunds"][0]["clawedBackUnits"] == 500  # not taken twice
    assert _inquiries(paymob) == [{"transaction_id": 888001}]  # the second call found nothing open
    [closed] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert closed.after["refund_id"] == str(refund)
    assert len(audit_rows(sm, AuditAction.PAYMENT_RECONCILE)) == 2


def test_a_partial_refund_is_visible_only_when_paymob_reports_the_prior_total_plus_it(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, amount_minor=10000, paymob_txn_id=51)
    _add_refund(
        sm, payment, admin, status=RefundStatus.succeeded, amount=3000, age=timedelta(hours=5)
    )
    refund = _add_refund(
        sm, payment, admin, status=RefundStatus.unknown, amount=2000, age=timedelta(minutes=5)
    )
    paymob = FakePaymobClient()
    paymob.transaction_result = {"id": 51, "refunded_amount_cents": 3000}  # only the old one
    client = _client(sm, admin, paymob)

    _post_reconcile(client, payment)
    assert _refund_status(sm, refund) is RefundStatus.unknown  # young, not visible: waits

    paymob.transaction_result = {"id": 51, "refunded_amount_cents": 5000}
    resp = _post_reconcile(client, payment)
    assert _refund_status(sm, refund) is RefundStatus.succeeded
    assert resp.json()["status"] == "partially_refunded"


def test_an_unknown_void_is_settled_by_is_voided(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, paymob_txn_id=61)
    void = _add_refund(
        sm,
        payment,
        admin,
        status=RefundStatus.unknown,
        amount=10000,
        age=timedelta(minutes=5),
        kind=RefundKind.void,
    )
    paymob = FakePaymobClient()
    paymob.transaction_result = {"id": 61, "is_voided": False}
    client = _client(sm, admin, paymob)
    _post_reconcile(client, payment)
    assert _refund_status(sm, void) is RefundStatus.unknown

    paymob.transaction_result = {"id": 61, "is_voided": True}
    resp = _post_reconcile(client, payment)

    assert _refund_status(sm, void) is RefundStatus.succeeded
    assert resp.json()["status"] == "voided"


def test_an_invisible_refund_waits_while_young_and_fails_after_sixty_minutes(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """UD-3 (b): keep it pending and recheck for 60 minutes, then mark it failed."""
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, amount_minor=10000, paymob_txn_id=71)
    young = _add_refund(
        sm, payment, admin, status=RefundStatus.unknown, amount=100, age=timedelta(minutes=59)
    )
    paymob = FakePaymobClient()
    paymob.transaction_result = {"id": 71, "refunded_amount_cents": 0}
    client = _client(sm, admin, paymob)

    _post_reconcile(client, payment)
    assert _refund_status(sm, young) is RefundStatus.unknown
    assert audit_rows(sm, AuditAction.PAYMENT_REFUND_FAILED) == []

    with sm.begin() as session:
        row = session.get(PaymentRefund, young)
        assert row is not None
        row.created_at = NOW - timedelta(minutes=61)
    resp = _post_reconcile(client, payment)

    assert _refund_status(sm, young) is RefundStatus.failed
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_FAILED)) == 1
    assert resp.json()["status"] == "paid"  # nothing moved: a new refund is allowed again


def test_an_unknown_to_paymob_transaction_counts_as_not_visible(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, paymob_txn_id=81)
    old = _add_refund(
        sm, payment, admin, status=RefundStatus.unknown, amount=100, age=timedelta(hours=2)
    )
    paymob = FakePaymobClient()
    paymob.transaction_result = None  # inquire_by_transaction answers None for a 404

    _post_reconcile(_client(sm, admin, paymob), payment)

    assert _refund_status(sm, old) is RefundStatus.failed


def test_a_stale_requested_refund_is_settled_like_unknown(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """A crash after Paymob answered leaves ``requested``; reconcile inquires and records it."""
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, amount_minor=10000, paymob_txn_id=91)
    visible = _add_refund(
        sm, payment, admin, status=RefundStatus.requested, amount=4000, age=timedelta(minutes=30)
    )
    paymob = FakePaymobClient()
    paymob.transaction_result = {"id": 91, "refunded_amount_cents": 4000}

    resp = _post_reconcile(_client(sm, admin, paymob), payment)

    assert _refund_status(sm, visible) is RefundStatus.succeeded
    assert resp.json()["status"] == "partially_refunded"


def test_a_stale_requested_refund_that_paymob_never_saw_waits_then_fails(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, amount_minor=10000, paymob_txn_id=92)
    row = _add_refund(
        sm, payment, admin, status=RefundStatus.requested, amount=4000, age=timedelta(minutes=30)
    )
    paymob = FakePaymobClient()
    paymob.transaction_result = {"id": 92, "refunded_amount_cents": 0}
    client = _client(sm, admin, paymob)

    _post_reconcile(client, payment)
    assert _refund_status(sm, row) is RefundStatus.requested  # under an hour: still waiting

    with sm.begin() as session:
        stored = session.get(PaymentRefund, row)
        assert stored is not None
        stored.created_at = NOW - timedelta(hours=2)
    _post_reconcile(client, payment)

    assert _refund_status(sm, row) is RefundStatus.failed


def test_a_young_requested_refund_is_a_live_call_and_is_not_inquired(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """The threshold sits above the Paymob client timeout, so cleanup cannot race a live call."""
    assert timedelta(seconds=PAYMOB_SETTINGS.timeout_seconds) < payments_repo.REFUND_STUCK_AFTER
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, paymob_txn_id=93)
    row = _add_refund(
        sm, payment, admin, status=RefundStatus.requested, amount=100, age=timedelta(seconds=30)
    )
    paymob = FakePaymobClient()
    paymob.transaction_result = {"id": 93, "refunded_amount_cents": 100}

    _post_reconcile(_client(sm, admin, paymob), payment)

    assert _refund_status(sm, row) is RefundStatus.requested
    assert _inquiries(paymob) == []


def test_an_inquiry_failure_is_502_leaves_the_refund_unknown_and_keeps_the_reconcile_audit(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, paymob_txn_id=101)
    refund = _add_refund(
        sm, payment, admin, status=RefundStatus.unknown, amount=100, age=timedelta(hours=2)
    )
    paymob = FakePaymobClient()
    paymob.transaction_result = PaymobError("Paymob GET transactions failed with HTTP 503")

    resp = _post_reconcile(_client(sm, admin, paymob), payment)

    assert resp.status_code == 502, resp.text
    assert resp.json()["detail"]["code"] == "paymob_inquiry_failed"
    assert _refund_status(sm, refund) is RefundStatus.unknown  # even though it is over an hour old
    assert audit_rows(sm, AuditAction.PAYMENT_REFUND_FAILED) == []
    assert len(audit_rows(sm, AuditAction.PAYMENT_RECONCILE)) == 1


def test_a_refund_settled_by_someone_else_in_between_is_not_closed_twice(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, amount_minor=10000, paymob_txn_id=111)
    refund = _add_refund(
        sm, payment, admin, status=RefundStatus.succeeded, amount=10000, age=timedelta(hours=1)
    )
    service = _service(sm, FakePaymobClient())

    service._close_refund(
        refund,
        outcome=RefundStatus.failed,
        response={},
        admin_user_id=admin,
        reason="late duplicate",
    )

    assert _refund_status(sm, refund) is RefundStatus.succeeded
    assert audit_rows(sm, AuditAction.PAYMENT_REFUND_FAILED) == []


def test_a_payment_with_no_paymob_transaction_has_nothing_to_inquire(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student)  # never charged: no paymob_txn_id
    _add_refund(sm, payment, admin, status=RefundStatus.unknown, amount=100, age=timedelta(hours=2))
    paymob = FakePaymobClient()

    resp = _post_reconcile(_client(sm, admin, paymob), payment)

    assert resp.status_code == 200
    assert _inquiries(paymob) == []
