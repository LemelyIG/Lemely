"""Refunds and voids (spec §6, §8 area 3): row first, Paymob second, unspent units clawed back.

Paymob is never reached: every call goes to ``FakePaymobClient`` (scripted results, recorded
calls). Each guard below was proved red by mutating the service (see the task report).
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import select
from structlog.testing import capture_logs

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.admin_billing_repo import AdminConflictError, AuditAction
from lemely.db.admin_payments_repo import AdminPaymentsService
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.billing_ops import PaymentRefund, RefundKind, RefundStatus
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.usage import (
    GrantKind,
    UsageEntry,
    UsageEntryKind,
    UsageGrant,
    UsageGrantBalance,
)
from lemely.io.paymob.client import PaymobError, PaymobNotConfigured
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.routers import admin_billing_payments
from lemely.web.routers.admin_billing_payments import get_admin_payments_service
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_payment,
    add_plan_tier,
    add_rate,
    add_subscription,
    add_user,
    audit_rows,
    billing_database,
    emptied_after,
    grant,
    metered_job,
    service_overrides,
)
from tests.paymob_fixtures import PAYMOB_SETTINGS
from tests.tutoring_app import app_with_routers

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

BASE = "/api/admin/billing/payments"


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
    sm: sessionmaker[Session],
    admin: uuid.UUID,
    paymob: FakePaymobClient | None = None,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    """The whole app plus this lane's router (mounted by ``app.py`` when the lead adds it)."""
    fake = paymob or FakePaymobClient()
    app = app_with_routers(admin_billing_payments.router)
    app.dependency_overrides.update(service_overrides(sm, fake))
    app.dependency_overrides[get_admin_payments_service] = lambda: _service(sm, fake)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin), role=Role.platform_admin.value
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _pack_bought_and_partly_spent(sm: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    """A paid 10,000-piaster pack of 500 units, 200 of them spent. Returns (student, payment)."""
    student = add_user(sm, Role.student)
    payment = add_payment(
        sm, payer=student, amount_minor=10000, paymob_order_id=777001, paymob_txn_id=888001
    )
    grant(sm, student, units=500, payment_id=payment)
    add_rate(sm, "mark_paper")
    metered_job(
        sm,
        student,
        [Payer(owner_user_id=student, scope=GrantScope.CREDITS)],
        low=150,
        high=250,
        cost=Decimal("0.2"),
    )
    return student, payment


def _credits(sm: sessionmaker[Session], admin: uuid.UUID, student: uuid.UUID) -> int:
    body = _client(sm, admin).get(f"/api/admin/billing/customers/{student}").json()
    return int(body["balance"]["creditsAvailable"])


def _refund(
    client: TestClient, payment: uuid.UUID, amount: int | None = None, reason: str = "goodwill"
) -> Any:
    return client.post(f"{BASE}/{payment}/refund", json={"amountMinor": amount, "reason": reason})


def _statuses(sm: sessionmaker[Session]) -> list[RefundStatus]:
    with sm() as session:
        return list(
            session.scalars(select(PaymentRefund.status).order_by(PaymentRefund.created_at))
        )


def _payment_status(sm: sessionmaker[Session], payment: uuid.UUID) -> PaymentStatus:
    with sm() as session:
        row = session.get(Payment, payment)
        assert row is not None
        return row.status


def _set_purpose(sm: sessionmaker[Session], payment: uuid.UUID, purpose: PaymentPurpose) -> None:
    with sm.begin() as session:
        row = session.get(Payment, payment)
        assert row is not None
        row.purpose = purpose


# -- the router guard ---------------------------------------------------------------


def test_the_payments_router_carries_its_own_platform_admin_guard() -> None:
    [dependency] = admin_billing_payments.router.dependencies
    guard = dependency.dependency
    assert guard is not None
    cells = dict(zip(guard.__code__.co_freevars, guard.__closure__ or (), strict=True))
    assert cells["allowed_values"].cell_contents == frozenset({"platform_admin"})


def test_a_non_admin_cannot_refund(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    client = _client(sm, admin, paymob)
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id=str(admin), role=Role.teacher.value
    )
    assert _refund(client, payment).status_code == 403
    assert client.post(f"{BASE}/{payment}/void", json={"reason": "no way"}).status_code == 403
    assert paymob.calls == []


# -- the happy paths ----------------------------------------------------------------


def test_a_full_refund_claws_back_only_unspent_units(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    resp = _refund(_client(sm, admin, paymob), payment, None, "duplicate purchase")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["refundedMinor"]) == ("refunded", 10000)
    [refund] = body["refunds"]
    assert (refund["status"], refund["clawedBackUnits"]) == ("succeeded", 300)
    assert (refund["paymentId"], refund["currency"]) == (str(payment), "EGP")
    assert paymob.calls == [("refund", {"transaction_id": 888001, "amount_cents": 10000})]
    assert _credits(sm, admin, student) == 0
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_REQUESTED)) == 1
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert (done.before["status"], done.after["status"]) == ("paid", "refunded")  # type: ignore[index]
    assert done.after["clawed_back_units"] == 300  # type: ignore[index]


def test_the_refund_row_exists_before_paymob_is_called(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    seen: list[RefundStatus] = []

    class Inspecting(FakePaymobClient):
        def refund(self, **kwargs: Any) -> dict[str, Any]:
            seen.extend(_statuses(sm))
            return {"id": 1, "success": True}

    _refund(_client(sm, admin, Inspecting()), payment, 4000, "partial")
    assert seen == [RefundStatus.requested]


def test_paymob_is_called_with_no_database_transaction_open(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """The payment row is lockable (and writable) while Paymob is being called."""
    _, payment = _pack_bought_and_partly_spent(sm)
    locked: list[bool] = []

    class Probing(FakePaymobClient):
        def refund(self, **kwargs: Any) -> dict[str, Any]:
            with sm.begin() as session:
                session.execute(
                    sa.text("SET LOCAL lock_timeout = '300ms'"),
                )
                session.execute(
                    sa.select(Payment.id).where(Payment.id == payment).with_for_update()
                ).all()
                locked.append(True)
            return {"id": 1, "success": True}

    assert _refund(_client(sm, admin, Probing()), payment, 4000).status_code == 200
    assert locked == [True]


def test_a_partial_refund_keeps_the_credits_until_the_rest_is_refunded(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student, payment = _pack_bought_and_partly_spent(sm)
    client = _client(sm, admin)
    partial = _refund(client, payment, 4000)
    assert (partial.json()["status"], partial.json()["refundedMinor"]) == (
        "partially_refunded",
        4000,
    )
    assert _credits(sm, admin, student) == 300
    rest = _refund(client, payment, None, "rest")
    assert (rest.json()["status"], rest.json()["refundedMinor"]) == ("refunded", 10000)
    assert rest.json()["refunds"][-1]["amountMinor"] == 6000
    assert _credits(sm, admin, student) == 0


def test_an_auto_topup_is_clawed_back_like_a_pack(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student, payment = _pack_bought_and_partly_spent(sm)
    _set_purpose(sm, payment, PaymentPurpose.auto_topup)
    body = _refund(_client(sm, admin), payment).json()
    assert body["refunds"][0]["clawedBackUnits"] == 300
    assert _credits(sm, admin, student) == 0


@pytest.mark.parametrize(
    ("purpose", "effect_key", "effect"),
    [
        (PaymentPurpose.subscription_first, "subscription_effect", "none"),
        (PaymentPurpose.subscription_renewal, "subscription_effect", "none"),
        (PaymentPurpose.upgrade_proration, "purpose_effect", "money_only"),
        (PaymentPurpose.extra_seats, "purpose_effect", "money_only"),
    ],
)
def test_other_purposes_without_a_subscription_refund_money_only_and_say_so_in_the_audit(
    sm: sessionmaker[Session],
    admin: uuid.UUID,
    purpose: PaymentPurpose,
    effect_key: str,
    effect: str,
) -> None:
    student, payment = _pack_bought_and_partly_spent(sm)
    _set_purpose(sm, payment, purpose)
    body = _refund(_client(sm, admin), payment).json()
    assert (body["status"], body["refunds"][0]["clawedBackUnits"]) == ("refunded", 0)
    assert _credits(sm, admin, student) == 300  # nothing was taken back
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after[effect_key] == effect  # type: ignore[index]


def test_void_voids_and_claws_back(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    resp = _client(sm, admin, paymob).post(
        f"{BASE}/{payment}/void", json={"reason": "same-day mistake"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "voided"
    assert resp.json()["refunds"][0]["kind"] == "void"
    assert paymob.calls == [("void", {"transaction_id": 888001})]
    assert _credits(sm, admin, student) == 0
    assert len(audit_rows(sm, AuditAction.PAYMENT_VOID_REQUESTED)) == 1


# -- what is refundable -------------------------------------------------------------


def test_more_than_the_remainder_is_422_and_touches_nothing(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    resp = _refund(_client(sm, admin, paymob), payment, 10001, "too much")
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "refund_amount_out_of_range"
    assert paymob.calls == []
    assert audit_rows(sm, AuditAction.PAYMENT_REFUND_REQUESTED) == []
    assert _statuses(sm) == []


def test_a_dashboard_refund_seen_only_in_the_callback_reduces_the_remainder(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(
        sm,
        payer=student,
        amount_minor=10000,
        paymob_txn_id=5,
        status=PaymentStatus.partially_refunded,
        last_callback={"is_refunded": True, "refunded_amount_cents": 7000},
    )

    class CallbackFollows(FakePaymobClient):
        """Paymob sends the parent callback with the new total, as Phase 02 records it."""

        def refund(self, **kwargs: Any) -> dict[str, Any]:
            result = super().refund(**kwargs)
            with sm.begin() as session:
                row = session.get(Payment, payment)
                assert row is not None
                total = row.last_callback["refunded_amount_cents"] + kwargs["amount_cents"]  # type: ignore[index]
                row.last_callback = {"is_refunded": True, "refunded_amount_cents": total}
            return result  # type: ignore[no-any-return]

    paymob = CallbackFollows()
    client = _client(sm, admin, paymob)
    over = _refund(client, payment, 4000, "over")
    assert over.status_code == 422
    assert over.json()["detail"]["code"] == "refund_amount_out_of_range"
    assert paymob.calls == []
    rest = _refund(client, payment, None, "the rest")
    assert rest.status_code == 200, rest.text
    assert paymob.calls == [("refund", {"transaction_id": 5, "amount_cents": 3000})]
    assert (rest.json()["status"], rest.json()["refundedMinor"]) == ("refunded", 10000)


def test_void_after_a_partial_refund_is_409(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    client = _client(sm, admin)
    _refund(client, payment, 1000, "part")
    resp = client.post(f"{BASE}/{payment}/void", json={"reason": "void it"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "not_voidable"


def test_void_after_a_dashboard_refund_is_409_even_while_the_status_still_says_paid(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(
        sm,
        payer=student,
        paymob_txn_id=5,
        status=PaymentStatus.paid,
        last_callback={"refunded_amount_cents": 500},
    )
    paymob = FakePaymobClient()
    resp = _client(sm, admin, paymob).post(f"{BASE}/{payment}/void", json={"reason": "void it"})
    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "not_voidable")
    assert paymob.calls == []


def test_a_voided_payment_offers_no_refund_and_no_second_void(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """The row shows ``refundedMinor`` 0 for a void (DV-19): the gate is the STATUS."""
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    client = _client(sm, admin, paymob)
    voided = client.post(f"{BASE}/{payment}/void", json={"reason": "mistake"})
    assert (voided.json()["status"], voided.json()["refundedMinor"]) == ("voided", 0)
    refund = _refund(client, payment, None, "again")
    assert (refund.status_code, refund.json()["detail"]["code"]) == (409, "not_refundable")
    second = client.post(f"{BASE}/{payment}/void", json={"reason": "again"})
    assert (second.status_code, second.json()["detail"]["code"]) == (409, "not_voidable")
    assert [name for name, _ in paymob.calls] == ["void"]


@pytest.mark.parametrize(
    "status", [PaymentStatus.failed, PaymentStatus.created, PaymentStatus.refunded]
)
def test_an_unpaid_or_fully_refunded_payment_is_not_refundable(
    sm: sessionmaker[Session], admin: uuid.UUID, status: PaymentStatus
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, status=status, paymob_txn_id=1)
    resp = _refund(_client(sm, admin), payment, None, "not paid")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "not_refundable"
    assert _payment_status(sm, payment) is status


def test_a_payment_paymob_never_charged_has_no_transaction_to_refund(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, paymob_txn_id=None)
    paymob = FakePaymobClient()
    resp = _refund(_client(sm, admin, paymob), payment)
    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "no_paymob_transaction")
    assert paymob.calls == []
    assert _statuses(sm) == []


def test_an_unknown_payment_is_404_and_a_short_reason_is_422(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = _client(sm, admin)
    missing = _refund(client, uuid.uuid4())
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "payment_not_found")
    _, payment = _pack_bought_and_partly_spent(sm)
    assert _refund(client, payment, None, "x").status_code == 422
    assert _statuses(sm) == []


# -- Paymob's answer (DV-18) --------------------------------------------------------


def test_a_paymob_refusal_fails_the_refund_and_a_new_refund_is_allowed(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    paymob.refund_result = PaymobError("declined", status_code=400, body={"detail": "no"})
    client = _client(sm, admin, paymob)
    resp = _refund(client, payment, None, "try")
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"
    assert resp.json()["refunds"][0]["status"] == "failed"
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_FAILED)) == 1
    paymob.refund_result = {"id": 2, "success": True}
    again = _refund(client, payment, None, "retry by hand")
    assert again.status_code == 200
    assert again.json()["status"] == "refunded"
    assert len(paymob.calls) == 2


@pytest.mark.parametrize(
    "error",
    [
        PaymobError("gateway", status_code=503, body={}),
        PaymobError("timed out", timeout=True),
        PaymobError("connection reset"),
    ],
    ids=["503", "timeout", "transport"],
)
def test_an_unclear_failure_leaves_the_refund_unknown_and_blocks_a_retry(
    sm: sessionmaker[Session], admin: uuid.UUID, error: PaymobError
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    paymob.refund_result = error
    client = _client(sm, admin, paymob)
    with capture_logs() as logs:
        first = _refund(client, payment, None, "try")
    assert first.json()["refunds"][0]["status"] == "unknown"
    assert first.json()["status"] == "paid"
    [alert] = [e for e in logs if e["event"] == "admin_refund_outcome_unknown"]
    assert alert["alert"] is True
    assert alert["payment_id"] == str(payment)
    assert alert["refund_id"] == first.json()["refunds"][0]["id"]
    second = _refund(client, payment, None, "again")
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "refund_in_flight"
    assert len(paymob.calls) == 1
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_UNKNOWN)) == 1


def test_a_5xx_is_unknown_even_when_the_client_did_not_flag_it(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """``billing_repo._outcome_unknown`` is the rule, not ``exc.outcome_unknown`` (audit I6)."""
    error = PaymobError("bad gateway", status_code=502, body={}, outcome_unknown=False)
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    paymob.refund_result = error
    body = _refund(_client(sm, admin, paymob), payment).json()
    assert body["refunds"][0]["status"] == "unknown"


def test_a_credential_that_is_not_configured_is_a_failure_because_nothing_was_sent(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    paymob.refund_result = PaymobNotConfigured("no secret key")
    body = _refund(_client(sm, admin, paymob), payment).json()
    assert body["refunds"][0]["status"] == "failed"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"id": 1, "success": True, "pending": True}, RefundStatus.unknown),
        ({"id": 1, "success": False, "pending": True}, RefundStatus.unknown),
        ({"id": 1, "success": False, "pending": False}, RefundStatus.failed),
        ({"id": 1, "success": False}, RefundStatus.failed),
        ({"id": 1, "success": True, "pending": False}, RefundStatus.succeeded),
        ({"id": 1}, RefundStatus.unknown),
        ({"id": 1, "success": "true"}, RefundStatus.unknown),
        (["not", "an", "object"], RefundStatus.unknown),
    ],
)
def test_a_2xx_answer_is_classified_by_its_success_and_pending_flags(
    sm: sessionmaker[Session], admin: uuid.UUID, answer: Any, expected: RefundStatus
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    paymob.refund_result = answer
    _refund(_client(sm, admin, paymob), payment)
    assert _statuses(sm) == [expected]


def test_the_stored_paymob_response_is_redacted(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    paymob.refund_result = {
        "id": 9,
        "success": True,
        "pending": False,
        "amount_cents": 10000,
        "is_refund": True,
        "is_void": False,
        "created_at": "2026-11-05T12:00:00",
        "source_data": {"pan": "2346", "sub_type": "MasterCard"},
        "token": "tok_secret",
        "data": {"card_holder_name": "Sara Ali"},
    }
    _refund(_client(sm, admin, paymob), payment)
    with sm() as session:
        stored = session.scalars(select(PaymentRefund.paymob_response)).one()
    assert stored == {
        "id": 9,
        "success": True,
        "pending": False,
        "amount_cents": 10000,
        "is_refund": True,
        "is_void": False,
        "created_at": "2026-11-05T12:00:00",
    }


# -- ordering and races -------------------------------------------------------------


def test_a_crash_between_the_call_and_the_outcome_leaves_the_requested_row(
    sm: sessionmaker[Session],
) -> None:
    """Row before call: the row survives anything that happens after Paymob is called."""

    class Crash(BaseException):
        pass

    class Crashing(FakePaymobClient):
        def refund(self, **kwargs: Any) -> dict[str, Any]:
            super().refund(**kwargs)
            raise Crash

    _, payment = _pack_bought_and_partly_spent(sm)
    admin = add_user(sm, Role.platform_admin)
    service = _service(sm, Crashing())
    with pytest.raises(Crash):
        service.refund(payment, amount_minor=None, admin_user_id=admin, reason="crash")
    assert _statuses(sm) == [RefundStatus.requested]
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_REQUESTED)) == 1
    with pytest.raises(AdminConflictError) as blocked:
        service.refund(payment, amount_minor=None, admin_user_id=admin, reason="again")
    assert blocked.value.code == "refund_in_flight"


def test_a_callback_that_got_there_first_is_never_lowered_and_clawback_runs_once(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """Phase 02 moves the status on the parent callback before transaction 2 runs."""
    student, payment = _pack_bought_and_partly_spent(sm)

    class CallbackFirst(FakePaymobClient):
        def refund(self, **kwargs: Any) -> dict[str, Any]:
            with sm.begin() as session:
                row = session.get(Payment, payment)
                assert row is not None
                row.status = PaymentStatus.refunded
                row.last_callback = {"is_refunded": True, "refunded_amount_cents": 10000}
            return {"id": 1, "success": True}

    body = _refund(_client(sm, admin, CallbackFirst()), payment).json()
    assert body["status"] == "refunded"
    assert body["refunds"][0]["clawedBackUnits"] == 300
    assert _credits(sm, admin, student) == 0
    with sm() as session:
        entries = session.scalars(
            select(UsageEntry).where(UsageEntry.kind == UsageEntryKind.refund)
        ).all()
    assert len(entries) == 1


def test_a_partial_console_refund_never_lowers_a_status_the_callback_already_raised(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)

    class CallbackFirst(FakePaymobClient):
        def refund(self, **kwargs: Any) -> dict[str, Any]:
            with sm.begin() as session:
                row = session.get(Payment, payment)
                assert row is not None
                row.status = PaymentStatus.refunded
                row.last_callback = {"refunded_amount_cents": 10000}
            return {"id": 1, "success": True}

    body = _refund(_client(sm, admin, CallbackFirst()), payment, 4000).json()
    assert body["status"] == "refunded"


def test_a_void_callback_that_got_there_first_is_never_lowered_to_refunded(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)

    class VoidFirst(FakePaymobClient):
        def refund(self, **kwargs: Any) -> dict[str, Any]:
            with sm.begin() as session:
                row = session.get(Payment, payment)
                assert row is not None
                row.status = PaymentStatus.voided
                row.last_callback = {"is_voided": True}
            return {"id": 1, "success": True}

    body = _refund(_client(sm, admin, VoidFirst()), payment).json()
    assert body["status"] == "voided"


def test_two_refunds_started_together_make_one_paymob_call_and_one_409(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    inside = threading.Event()
    release = threading.Event()

    class Slow(FakePaymobClient):
        def refund(self, **kwargs: Any) -> dict[str, Any]:
            result = super().refund(**kwargs)
            inside.set()
            release.wait(timeout=10)
            return result  # type: ignore[no-any-return]

    paymob = Slow()
    first_client = _client(sm, admin, paymob)
    second_client = _client(sm, admin, paymob)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_refund, first_client, payment, None, "first")
        assert inside.wait(timeout=10)
        second = pool.submit(_refund, second_client, payment, None, "second")
        blocked = second.result(timeout=20)
        release.set()
        done = first.result(timeout=20)
    assert done.status_code == 200
    assert (blocked.status_code, blocked.json()["detail"]["code"]) == (409, "refund_in_flight")
    assert len(paymob.calls) == 1
    assert _statuses(sm) == [RefundStatus.succeeded]


def test_a_burst_of_refunds_calls_paymob_once(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    """No hand-timed gate: six simultaneous requests, whatever the interleaving."""
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    clients = [_client(sm, admin, paymob) for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = sorted(
            f.result(timeout=60).status_code
            for f in [pool.submit(_refund, c, payment, None, "burst") for c in clients]
        )
    assert len(paymob.calls) == 1
    # One refund is made; a request that arrives afterwards finds a payment that is not refundable.
    assert codes.count(200) == 1
    assert set(codes) <= {200, 409}


def test_every_path_writes_a_requested_row_and_one_closing_row(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    client = _client(sm, admin, paymob)
    paymob.refund_result = PaymobError("declined", status_code=400, body={})
    _refund(client, payment, 1000, "first try")
    paymob.refund_result = {"id": 1, "success": True}
    _refund(client, payment, 1000, "second try")
    paymob.refund_result = PaymobError("gateway", status_code=503, body={})
    _refund(client, payment, 1000, "third try")
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_REQUESTED)) == 3
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_FAILED)) == 1
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)) == 1
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_UNKNOWN)) == 1
    assert [r.kind for r in _rows(sm)] == [RefundKind.refund] * 3


def _rows(sm: sessionmaker[Session]) -> list[PaymentRefund]:
    with sm() as session:
        return list(session.scalars(select(PaymentRefund).order_by(PaymentRefund.created_at)))


# -- Part B: a subscription payment (Phase 05's on_payment_refunded, UD-6 (a)) --------------------


def _subscribed(
    sm: sessionmaker[Session],
    *,
    purpose: PaymentPurpose = PaymentPurpose.subscription_first,
    older_period: bool = False,
) -> dict[str, Any]:
    """A student on an active plan whose latest period was paid by one 10,000-piaster payment."""
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm, price_minor=10000)
    sub = add_subscription(
        sm, student, tier, start=NOW - timedelta(days=4), end=NOW + timedelta(days=26)
    )
    payment = add_payment(
        sm,
        payer=student,
        purpose=PaymentPurpose.credit_pack,
        amount_minor=10000,
        paymob_txn_id=4242,
    )
    with sm.begin() as session:
        row = session.get(Payment, payment)
        assert row is not None
        row.purpose = purpose
        row.credit_pack_id = None
        row.subscription_id = sub
        row.plan_tier_id = tier
        period = session.scalars(
            sa.select(SubscriptionPeriod).where(SubscriptionPeriod.subscription_id == sub)
        ).one()
        period.payment_id = payment
        period.terms_version = 1
        if older_period:  # the paid period ended; a later one is in force at NOW
            newer_start, newer_end = period.period_start, period.period_end
            period.period_start = newer_start - timedelta(days=30)
            period.period_end = newer_start
            session.flush()
            session.add(
                SubscriptionPeriod(
                    subscription_id=sub, period_start=newer_start, period_end=newer_end
                )
            )
    allowance = grant(
        sm, student, units=1000, kind=GrantKind.period_allowance, visible=False, payment_id=payment
    )
    return {"student": student, "sub": sub, "payment": payment, "tier": tier, "grant": allowance}


def _sub_status(sm: sessionmaker[Session], sub: uuid.UUID) -> SubscriptionStatus:
    with sm() as session:
        row = session.get(Subscription, sub)
        assert row is not None
        return row.status


@pytest.mark.parametrize(
    "purpose", [PaymentPurpose.subscription_first, PaymentPurpose.subscription_renewal]
)
def test_a_full_refund_of_the_latest_period_ends_the_plan_and_claws_back(
    sm: sessionmaker[Session], admin: uuid.UUID, purpose: PaymentPurpose
) -> None:
    w = _subscribed(sm, purpose=purpose)
    body = _refund(_client(sm, admin), w["payment"]).json()
    assert body["status"] == "refunded"
    assert body["refunds"][0]["clawedBackUnits"] == 1000
    assert _sub_status(sm, w["sub"]) is SubscriptionStatus.cancelled
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["subscription_effect"] == "plan_ended"  # type: ignore[index]
    assert "pending_phase05" not in str(done.after)


def test_a_partial_refund_of_a_subscription_payment_changes_nothing(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _subscribed(sm)
    body = _refund(_client(sm, admin), w["payment"], 3000).json()
    assert (body["status"], body["refunds"][0]["clawedBackUnits"]) == ("partially_refunded", 0)
    assert _sub_status(sm, w["sub"]) is SubscriptionStatus.active
    assert _credits_total(sm, w["student"]) == 1000


def test_a_full_refund_of_an_older_period_leaves_the_plan_and_alerts(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _subscribed(sm, older_period=True)
    with capture_logs() as logs:
        body = _refund(_client(sm, admin), w["payment"]).json()
    assert body["status"] == "refunded"  # the money went back
    assert _sub_status(sm, w["sub"]) is SubscriptionStatus.active
    assert [e for e in logs if e["event"] == "subscription_old_period_refunded"]
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["subscription_effect"] == "none"  # type: ignore[index]


def test_a_subscription_void_ends_the_plan_too(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    w = _subscribed(sm)
    body = (
        _client(sm, admin).post(f"{BASE}/{w['payment']}/void", json={"reason": "same day"}).json()
    )
    assert body["status"] == "voided"
    assert _sub_status(sm, w["sub"]) is SubscriptionStatus.cancelled


def _credits_total(sm: sessionmaker[Session], user: uuid.UUID) -> int:
    with sm() as session:
        return int(
            session.scalar(
                sa.select(sa.func.coalesce(sa.func.sum(UsageGrantBalance.remaining), 0))
                .select_from(UsageGrant)
                .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
                .where(UsageGrant.owner_user_id == user)
            )
            or 0
        )


# -- Part C: reverse what the payment bought (UD-4) ----------------------------------------------


def _teacher_with_seats(
    sm: sessionmaker[Session], *, held: int = 3, bought: int = 2
) -> dict[str, Any]:
    teacher = add_user(sm, Role.teacher)
    tier = add_plan_tier(
        sm,
        code=f"teacher_{uuid.uuid4().hex[:8]}",
        audience="teacher",
        price_minor=30000,
        included_seats=1,
        extra_seat_price_minor=5000,
    )
    sub = add_subscription(sm, teacher, tier)
    payment = add_payment(
        sm,
        payer=teacher,
        purpose=PaymentPurpose.credit_pack,
        amount_minor=10000,
        paymob_txn_id=uuid.uuid4().int % 10**12,
    )
    with sm.begin() as session:
        row = session.get(Payment, payment)
        assert row is not None
        row.purpose = PaymentPurpose.extra_seats
        row.credit_pack_id = None
        row.subscription_id = sub
        row.seat_quantity = bought
        row.plan_tier_id = tier
        subscription = session.get(Subscription, sub)
        assert subscription is not None
        subscription.extra_seats = held
    return {"teacher": teacher, "tier": tier, "sub": sub, "payment": payment}


def _sub_row(sm: sessionmaker[Session], sub: uuid.UUID) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, sub)
        assert row is not None
        return row


def _reversing(client: TestClient, payment: uuid.UUID, amount: int | None = None) -> Any:
    return client.post(
        f"{BASE}/{payment}/refund",
        json={"amountMinor": amount, "reason": "undo it", "reverseChange": True},
    )


def test_reversing_extra_seats_schedules_the_reduction_and_audits_it(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _teacher_with_seats(sm, held=3, bought=2)
    resp = _reversing(_client(sm, admin), w["payment"])
    assert resp.status_code == 200, resp.text
    assert _sub_row(sm, w["sub"]).pending_extra_seats == 1
    with sm() as session:
        assert session.scalars(select(PaymentRefund.reverse_change)).one() is True
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["reverse_effect"] == "seat_reduction_scheduled"  # type: ignore[index]
    assert done.after["pending_extra_seats"] == 1  # type: ignore[index]
    [asked] = audit_rows(sm, AuditAction.PAYMENT_REFUND_REQUESTED)
    assert asked.after["reverse_change"] is True  # type: ignore[index]


def test_extra_seats_are_money_only_unless_the_admin_asks_to_reverse(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _teacher_with_seats(sm)
    assert _refund(_client(sm, admin), w["payment"]).status_code == 200
    assert _sub_row(sm, w["sub"]).pending_extra_seats is None
    with sm() as session:
        assert session.scalars(select(PaymentRefund.reverse_change)).one() is False


def test_a_reverse_the_seat_api_refuses_is_422_before_any_row_or_paymob_call(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _teacher_with_seats(sm)
    with sm.begin() as session:
        sub = session.get(Subscription, w["sub"])
        assert sub is not None
        sub.status = SubscriptionStatus.past_due
    paymob = FakePaymobClient()
    resp = _reversing(_client(sm, admin, paymob), w["payment"])
    assert (resp.status_code, resp.json()["detail"]["code"]) == (422, "reverse_unavailable")
    assert paymob.calls == [] and _statuses(sm) == []


def test_reversing_a_renewal_seat_charge_is_422_because_it_added_no_seats(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _teacher_with_seats(sm)
    with sm.begin() as session:
        row = session.get(Payment, w["payment"])
        assert row is not None
        row.dedupe_key = f"extra_seat_renewal:{uuid.uuid4()}:1"
    resp = _reversing(_client(sm, admin), w["payment"])
    assert (resp.status_code, resp.json()["detail"]["code"]) == (422, "reverse_unavailable")


def test_reversing_needs_the_whole_remaining_amount(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _teacher_with_seats(sm)
    paymob = FakePaymobClient()
    resp = _reversing(_client(sm, admin, paymob), w["payment"], 4000)
    assert (resp.status_code, resp.json()["detail"]["code"]) == (422, "reverse_needs_full_refund")
    assert paymob.calls == [] and _statuses(sm) == []


def test_a_reverse_that_stops_working_after_the_money_moved_is_audited_and_alerted(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """Never silent: the refund stands, and the audit row and an alert say the undo did not run."""
    w = _teacher_with_seats(sm)

    class PlanLapses(FakePaymobClient):
        def refund(self, **kwargs: Any) -> dict[str, Any]:
            with sm.begin() as session:
                sub = session.get(Subscription, w["sub"])
                assert sub is not None
                sub.status = SubscriptionStatus.past_due
            return {"id": 1, "success": True}

    with capture_logs() as logs:
        resp = _reversing(_client(sm, admin, PlanLapses()), w["payment"])
    assert resp.json()["status"] == "refunded"
    assert [e for e in logs if e["event"] == "admin_refund_reverse_unavailable"]
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["reverse_effect"] == "unavailable_after_refund"  # type: ignore[index]
    assert _sub_row(sm, w["sub"]).pending_extra_seats is None


def test_extra_seats_that_became_credits_keep_them_money_only_and_lose_them_on_reverse(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _teacher_with_seats(sm)
    grant(sm, w["teacher"], units=400, kind=GrantKind.credit_pack, payment_id=w["payment"])
    paymob = FakePaymobClient()
    kept = _refund(_client(sm, admin, paymob), w["payment"]).json()
    assert kept["refunds"][0]["clawedBackUnits"] == 0
    assert _sub_row(sm, w["sub"]).pending_extra_seats is None
    w2 = _teacher_with_seats(sm)
    grant(sm, w2["teacher"], units=400, kind=GrantKind.credit_pack, payment_id=w2["payment"])
    undone = _reversing(_client(sm, admin, paymob), w2["payment"]).json()
    assert undone["refunds"][0]["clawedBackUnits"] == 400
    assert _sub_row(sm, w2["sub"]).pending_extra_seats is None  # no seat was ever added


def test_a_subscription_payment_converted_to_credits_loses_them_on_reverse_and_ends_no_plan(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """UD-3: a stale checkout paid, no plan was activated, the money became credits."""
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm, price_minor=10000)
    sub = add_subscription(sm, student, tier)  # a live plan from another, paid period
    payment = add_payment(
        sm, payer=student, purpose=PaymentPurpose.credit_pack, amount_minor=10000, paymob_txn_id=9
    )
    with sm.begin() as session:
        row = session.get(Payment, payment)
        assert row is not None
        row.purpose = PaymentPurpose.subscription_first
        row.credit_pack_id = None
        row.subscription_id = sub
        row.plan_tier_id = tier
        row.grant_units = 400
    grant(sm, student, units=400, kind=GrantKind.credit_pack, payment_id=payment)
    with capture_logs() as logs:
        body = _reversing(_client(sm, admin), payment).json()
    assert body["refunds"][0]["clawedBackUnits"] == 400
    assert _sub_status(sm, sub) is SubscriptionStatus.active  # no plan was bought by this payment
    assert not [e for e in logs if str(e["event"]).startswith("subscription_")]
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["reverse_effect"] == "credits_clawed_back"  # type: ignore[index]
    assert "subscription_effect" not in done.after  # type: ignore[operator]


def test_a_converted_subscription_payment_keeps_its_credits_when_money_only(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm, price_minor=10000)
    sub = add_subscription(sm, student, tier)
    payment = add_payment(
        sm, payer=student, purpose=PaymentPurpose.credit_pack, amount_minor=10000, paymob_txn_id=9
    )
    with sm.begin() as session:
        row = session.get(Payment, payment)
        assert row is not None
        row.purpose = PaymentPurpose.subscription_first
        row.credit_pack_id = None
        row.subscription_id = sub
        row.plan_tier_id = tier
    grant(sm, student, units=400, kind=GrantKind.credit_pack, payment_id=payment)
    body = _refund(_client(sm, admin), payment).json()
    assert body["refunds"][0]["clawedBackUnits"] == 0
    assert _sub_status(sm, sub) is SubscriptionStatus.active


def _upgraded(
    sm: sessionmaker[Session], *, terms_version: int | None = 1, bill_prev: bool = True
) -> dict[str, Any]:
    """A student who upgraded mid-period: the period was paid on ``previous``, now on ``target``."""
    student = add_user(sm, Role.student)
    previous = add_plan_tier(sm, code="student_basic", price_minor=10000)
    target = add_plan_tier(sm, code="student_plus", price_minor=20000)
    sub = add_subscription(
        sm, student, target, start=NOW - timedelta(days=4), end=NOW + timedelta(days=26)
    )
    first = add_payment(sm, payer=student, amount_minor=10000, paymob_txn_id=1)
    upgrade = add_payment(
        sm, payer=student, amount_minor=6000, paymob_txn_id=2, created_at=NOW - timedelta(days=1)
    )
    with sm.begin() as session:
        for pid, purpose, tier in (
            (first, PaymentPurpose.subscription_first, previous if bill_prev else target),
            (upgrade, PaymentPurpose.upgrade_proration, target),
        ):
            row = session.get(Payment, pid)
            assert row is not None
            row.purpose = purpose
            row.credit_pack_id = None
            row.subscription_id = sub
            row.plan_tier_id = tier
        period = session.scalars(
            sa.select(SubscriptionPeriod).where(SubscriptionPeriod.subscription_id == sub)
        ).one()
        period.payment_id = first
        period.terms_version = terms_version
    return {
        "student": student,
        "previous": previous,
        "target": target,
        "sub": sub,
        "upgrade": upgrade,
    }


def test_reversing_an_upgrade_schedules_the_billed_previous_tier(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _upgraded(sm)
    resp = _reversing(_client(sm, admin), w["upgrade"])
    assert resp.status_code == 200, resp.text
    assert _sub_row(sm, w["sub"]).pending_plan_tier_id == w["previous"]
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["reverse_effect"] == "downgrade_scheduled"  # type: ignore[index]
    assert done.after["previous_plan_tier_id"] == str(w["previous"])  # type: ignore[index]


def test_an_upgrade_refund_without_reverse_leaves_the_plan(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _upgraded(sm)
    assert _refund(_client(sm, admin), w["upgrade"]).status_code == 200
    assert _sub_row(sm, w["sub"]).pending_plan_tier_id is None


@pytest.mark.parametrize("case", ["terms_unknown", "terms_not_recorded", "previous_not_recorded"])
def test_an_upgrade_whose_previous_tier_or_terms_are_not_recoverable_is_422(
    sm: sessionmaker[Session], admin: uuid.UUID, case: str
) -> None:
    w = _upgraded(
        sm,
        terms_version={"terms_unknown": 7, "terms_not_recorded": None, "previous_not_recorded": 1}[
            case
        ],
        bill_prev=case != "previous_not_recorded",
    )
    paymob = FakePaymobClient()
    resp = _reversing(_client(sm, admin, paymob), w["upgrade"])
    assert (resp.status_code, resp.json()["detail"]["code"]) == (422, "reverse_unavailable")
    assert paymob.calls == [] and _statuses(sm) == []


def test_reversing_a_credit_pack_is_the_clawback_a_full_refund_already_makes(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student, payment = _pack_bought_and_partly_spent(sm)
    body = _reversing(_client(sm, admin), payment).json()
    assert body["refunds"][0]["clawedBackUnits"] == 300
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["reverse_effect"] == "same_as_full_refund"  # type: ignore[index]


# -- the refunded-total lag ----------------------------------------------------------------------


def test_a_console_refund_hidden_behind_a_dashboard_refund_cannot_be_requested_twice(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """Dashboard 7000 plus console 3000, with Paymob's parent callback not yet back."""
    student = add_user(sm, Role.student)
    payment = add_payment(
        sm,
        payer=student,
        amount_minor=10000,
        paymob_txn_id=5,
        status=PaymentStatus.partially_refunded,
        last_callback={"is_refunded": True, "refunded_amount_cents": 7000},
    )
    paymob = FakePaymobClient()
    client = _client(sm, admin, paymob)
    first = _refund(client, payment, 3000, "the rest")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "refunded"
    again = _refund(client, payment, 3000, "same again")
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "not_refundable")
    assert len(paymob.calls) == 1


# -- review fixes (I1, I2, M1-M6) ----------------------------------------------------------------


def _pending_seats(sm: sessionmaker[Session], sub: uuid.UUID, value: int | None) -> None:
    with sm.begin() as session:
        row = session.get(Subscription, sub)
        assert row is not None
        row.pending_extra_seats = value


def test_the_seat_reverse_keeps_seats_an_earlier_scheduled_reduction_already_cut_to(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """Held 5 = 3 older + 2 from this payment; 3 are scheduled: undoing the 2 leaves 3, not 1."""
    w = _teacher_with_seats(sm, held=5, bought=2)
    _pending_seats(sm, w["sub"], 3)
    resp = _reversing(_client(sm, admin), w["payment"])
    assert resp.status_code == 200, resp.text
    assert _sub_row(sm, w["sub"]).pending_extra_seats == 3
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["reverse_effect"] == "already_scheduled"  # type: ignore[index]


def test_a_deeper_scheduled_reduction_is_never_raised_by_the_reverse(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _teacher_with_seats(sm, held=5, bought=2)
    _pending_seats(sm, w["sub"], 1)
    assert _reversing(_client(sm, admin), w["payment"]).status_code == 200
    assert _sub_row(sm, w["sub"]).pending_extra_seats == 1


def test_the_seat_reverse_lowers_a_reduction_that_still_holds_this_payments_seats(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """Held 5, 2 bought here, 4 scheduled: without this purchase the teacher holds 3."""
    w = _teacher_with_seats(sm, held=5, bought=2)
    _pending_seats(sm, w["sub"], 4)
    assert _reversing(_client(sm, admin), w["payment"]).status_code == 200
    assert _sub_row(sm, w["sub"]).pending_extra_seats == 3


def test_seats_bought_in_an_earlier_period_are_not_reversed(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _teacher_with_seats(sm)
    with sm.begin() as session:
        row = session.get(Payment, w["payment"])
        assert row is not None
        row.created_at = NOW - timedelta(days=40)
    paymob = FakePaymobClient()
    resp = _reversing(_client(sm, admin, paymob), w["payment"])
    assert (resp.status_code, resp.json()["detail"]["code"]) == (422, "reverse_unavailable")
    assert paymob.calls == []


def _third_tier_upgrade(
    sm: sessionmaker[Session], w: dict[str, Any], *, first_paid_at: datetime
) -> uuid.UUID:
    """basic (period paid) -> plus (``w['upgrade']``) -> pro. Returns pro's payment."""
    pro = add_plan_tier(sm, code=f"student_pro_{uuid.uuid4().hex[:6]}", price_minor=30000)
    second = add_payment(
        sm,
        payer=w["student"],
        amount_minor=5000,
        paymob_txn_id=3,
        paid_at=first_paid_at + timedelta(hours=1),
        created_at=NOW - timedelta(hours=2),
    )
    with sm.begin() as session:
        first = session.get(Payment, w["upgrade"])
        assert first is not None
        first.paid_at = first_paid_at
        row = session.get(Payment, second)
        assert row is not None
        row.purpose = PaymentPurpose.upgrade_proration
        row.credit_pack_id = None
        row.subscription_id = w["sub"]
        row.plan_tier_id = pro
        sub = session.get(Subscription, w["sub"])
        assert sub is not None
        sub.plan_tier_id = pro
    return second


def test_reversing_the_second_upgrade_schedules_the_tier_it_replaced_not_the_period_base(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """basic -> plus -> pro: reversing pro goes back to plus."""
    w = _upgraded(sm)
    second = _third_tier_upgrade(sm, w, first_paid_at=datetime.now(UTC) + timedelta(minutes=5))
    resp = _reversing(_client(sm, admin), second)
    assert resp.status_code == 200, resp.text
    assert _sub_row(sm, w["sub"]).pending_plan_tier_id == w["target"]  # plus, not basic
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["previous_plan_tier_id"] == str(w["target"])  # type: ignore[index]
    assert done.after["previous_tier_source"] == "previous_upgrade"  # type: ignore[index]


def test_the_first_upgrade_names_the_period_payment_as_its_source(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _upgraded(sm)
    _reversing(_client(sm, admin), w["upgrade"])
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["previous_tier_source"] == "period_payment"  # type: ignore[index]


def test_an_earlier_upgrade_whose_tier_terms_changed_since_is_not_restored(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """The plus terms in force now were written after the plus upgrade was paid."""
    w = _upgraded(sm)
    second = _third_tier_upgrade(sm, w, first_paid_at=NOW)
    paymob = FakePaymobClient()
    resp = _reversing(_client(sm, admin, paymob), second)
    assert (resp.status_code, resp.json()["detail"]["code"]) == (422, "reverse_unavailable")
    assert paymob.calls == [] and _statuses(sm) == []


def test_a_plan_already_ending_at_period_end_makes_the_upgrade_reverse_a_noop_success(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _upgraded(sm)
    with sm.begin() as session:
        sub = session.get(Subscription, w["sub"])
        assert sub is not None
        sub.cancel_at_period_end = True
    resp = _reversing(_client(sm, admin), w["upgrade"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "refunded"
    assert _sub_row(sm, w["sub"]).pending_plan_tier_id is None
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert done.after["reverse_effect"] == "plan_ends_at_period_end"  # type: ignore[index]


def test_the_upgrade_reverse_claws_back_unused_allowance_and_spent_units_stay_spent(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _upgraded(sm)
    grant(
        sm,
        w["student"],
        units=300,
        kind=GrantKind.period_allowance,
        visible=False,
        payment_id=w["upgrade"],
    )
    add_rate(sm, "mark_paper")
    metered_job(
        sm,
        w["student"],
        [Payer(owner_user_id=w["student"], scope=GrantScope.ALLOWANCE)],
        low=80,
        high=120,
        cost=Decimal("0.1"),
    )  # spends 100 units
    body = _reversing(_client(sm, admin), w["upgrade"]).json()
    assert body["refunds"][0]["clawedBackUnits"] == 200


def test_money_only_leaves_the_upgrade_allowance_alone(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _upgraded(sm)
    grant(
        sm,
        w["student"],
        units=300,
        kind=GrantKind.period_allowance,
        visible=False,
        payment_id=w["upgrade"],
    )
    body = _refund(_client(sm, admin), w["upgrade"]).json()
    assert body["refunds"][0]["clawedBackUnits"] == 0


def test_a_failure_recording_the_outcome_after_paymob_refunded_is_alerted(
    sm: sessionmaker[Session], admin: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lemely.db import admin_payments_repo as mod

    w = _teacher_with_seats(sm)

    def boom(self: Any, s: Any, payment: Any, refund: Any) -> dict[str, object]:
        raise RuntimeError("deadlock detected")

    monkeypatch.setattr(mod.AdminPaymentsService, "_apply_success", boom)
    paymob = FakePaymobClient()
    client = _client(sm, admin, paymob, raise_server_exceptions=False)
    with capture_logs() as logs:
        resp = _refund(client, w["payment"])
    assert resp.status_code == 500
    assert len(paymob.calls) == 1
    [alert] = [e for e in logs if e["event"] == "admin_refund_outcome_unrecorded"]
    assert alert["alert"] is True
    [row] = _rows(sm)
    assert row.status is RefundStatus.requested
    assert alert["refund_id"] == str(row.id) and alert["payment_id"] == str(w["payment"])
    assert alert["outcome"] == "succeeded"
    # and the stuck row blocks a second refund
    second = _refund(_client(sm, admin, paymob), w["payment"])
    assert second.json()["detail"]["code"] == "refund_in_flight"


def test_a_paymob_refusal_with_reverse_change_applies_no_reverse(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _teacher_with_seats(sm)
    paymob = FakePaymobClient()
    paymob.refund_result = PaymobError("refused", status_code=400)
    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        resp = _reversing(_client(sm, admin, paymob), w["payment"])
    assert resp.status_code == 200
    assert resp.json()["refunds"][0]["status"] == "failed"
    assert resp.json()["status"] == "paid"
    assert _sub_row(sm, w["sub"]).pending_extra_seats is None  # nothing was scheduled
    real = [e for e in logs if e["event"] == "seat_reduction_scheduled" and not e.get("dry_run")]
    assert real == []  # the only such line came from the dry run, which is marked
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_FAILED)
    assert "reverse_effect" not in done.after  # type: ignore[operator]


def test_the_dry_run_marks_its_lines_and_the_logger_drops_them() -> None:
    from lemely.runtime.logging import _drop_dry_run

    with pytest.raises(structlog.DropEvent):
        _drop_dry_run(None, "info", {"event": "seat_reduction_scheduled", "dry_run": True})
    assert _drop_dry_run(None, "info", {"event": "x"}) == {"event": "x"}


def test_the_seat_reverse_that_succeeds_logs_the_schedule_once_for_real(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    w = _teacher_with_seats(sm)
    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        assert _reversing(_client(sm, admin), w["payment"]).status_code == 200
    scheduled = [e for e in logs if e["event"] == "seat_reduction_scheduled"]
    assert [bool(e.get("dry_run")) for e in scheduled] == [True, False]
