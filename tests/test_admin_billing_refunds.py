"""Refunds and voids (spec §6, §8 area 3): row first, Paymob second, unspent units clawed back.

Paymob is never reached: every call goes to ``FakePaymobClient`` (scripted results, recorded
calls). Each guard below was proved red by mutating the service (see the task report).
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import select
from structlog.testing import capture_logs

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.admin_billing_repo import AdminConflictError, AuditAction
from lemely.db.admin_payments_repo import AdminPaymentsService
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus
from lemely.db.models.billing_ops import PaymentRefund, RefundKind, RefundStatus
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageEntry, UsageEntryKind
from lemely.io.paymob.client import PaymobError, PaymobNotConfigured
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.routers import admin_billing_payments
from lemely.web.routers.admin_billing_payments import get_admin_payments_service
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_payment,
    add_rate,
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
    sm: sessionmaker[Session], admin: uuid.UUID, paymob: FakePaymobClient | None = None
) -> TestClient:
    """The whole app plus this lane's router (mounted by ``app.py`` when the lead adds it)."""
    fake = paymob or FakePaymobClient()
    app = app_with_routers(admin_billing_payments.router)
    app.dependency_overrides.update(service_overrides(sm, fake))
    app.dependency_overrides[get_admin_payments_service] = lambda: _service(sm, fake)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin), role=Role.platform_admin.value
    )
    return TestClient(app)


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
        (PaymentPurpose.subscription_first, "subscription_effect", "pending_phase05"),
        (PaymentPurpose.subscription_renewal, "subscription_effect", "pending_phase05"),
        (PaymentPurpose.upgrade_proration, "purpose_effect", "money_only"),
        (PaymentPurpose.extra_seats, "purpose_effect", "money_only"),
    ],
)
def test_other_purposes_refund_money_only_and_say_so_in_the_audit(
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
