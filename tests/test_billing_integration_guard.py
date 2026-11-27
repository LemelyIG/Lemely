"""The per-payment integration guard in ``BillingService._apply_transaction`` (Phase 06 T3 review).

A transaction settles a payment only when it was taken on an integration that payment may use:

* a MOTO-charged payment (``dedupe_key`` set: auto top-up, the fallback seat charge) accepts only
  the MOTO integration;
* a checkout payment (no ``dedupe_key``: credit pack, upgrade, seat purchase, first subscription
  charge) accepts only the card and Apple Pay integrations, so a 3DS-required purchase can never
  settle through the no-3DS MOTO integration that Lemely carries chargeback liability for;
* a subscription renewal keeps Phase 05's rule (the plan's MOTO integration, any configured one).

"Accepted" is observed as a state change: every callback here is a decline (``success: false``),
which the guard lets through to ``failed`` and which a held-back callback leaves ``pending``. That
keeps the matrix independent of which paid handlers happen to be registered in the process.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa

from lemely.db.billing_repo import BillingService
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus, PaymobEvent
from lemely.db.models.enums import Role
from tests.merchant_charge_fixtures import (
    seed_pack,
    seed_payment_row,
    seed_user,
    throwaway_database,
)
from tests.paymob_fixtures import (
    CARD_INTEGRATION_ID,
    MOTO_INTEGRATION_ID,
    FakePaymobClient,
    transaction_obj,
)
from tests.subscription_fixtures import paymob_settings

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
APPLE_PAY_INTEGRATION_ID = 4569878
FOREIGN_INTEGRATION_ID = 9_999_999
SETTINGS = paymob_settings(apple_pay_integration_id=APPLE_PAY_INTEGRATION_ID)

_order_ids = iter(range(5_100_000, 5_200_000))
_txn_ids = iter(range(6_100_000, 6_200_000))

INTEGRATIONS = {
    "card": CARD_INTEGRATION_ID,
    "apple_pay": APPLE_PAY_INTEGRATION_ID,
    "moto": MOTO_INTEGRATION_ID,
    "foreign": FOREIGN_INTEGRATION_ID,
}

# (kind of payment, integration the transaction was taken on, accepted?)
MATRIX = [
    ("checkout", "card", True),
    ("checkout", "apple_pay", True),
    ("checkout", "moto", False),
    ("checkout", "foreign", False),
    ("moto_charge", "moto", True),
    ("moto_charge", "card", False),
    ("moto_charge", "apple_pay", False),
    ("moto_charge", "foreign", False),
    ("renewal", "moto", True),
    ("renewal", "foreign", False),
]


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


def _payment(sm: sessionmaker[Session], kind: str) -> tuple[uuid.UUID, int]:
    """A ``pending`` payment of ``kind`` with its Paymob order id."""
    payer = seed_user(sm, Role.student)
    order_id = next(_order_ids)
    extra: dict[str, Any] = {}
    if kind == "checkout":
        purpose = PaymentPurpose.credit_pack
        extra["credit_pack_id"] = seed_pack(sm)
    elif kind == "moto_charge":
        purpose = PaymentPurpose.auto_topup
        extra["dedupe_key"] = f"auto_topup:{order_id}:1"
    else:
        purpose = PaymentPurpose.subscription_renewal
    payment_id = seed_payment_row(
        sm,
        payer_id=payer,
        purpose=purpose,
        amount_minor=10_000,
        status=PaymentStatus.pending,
        paymob_order_id=order_id,
        **extra,
    )
    return payment_id, order_id


def _declined(
    sm: sessionmaker[Session], payment_id: uuid.UUID, order_id: int, integration: str
) -> dict[str, Any]:
    with sm() as session:
        reference = session.scalar(
            sa.select(Payment.special_reference).where(Payment.id == payment_id)
        )
    assert reference is not None
    obj = transaction_obj(
        txn_id=next(_txn_ids),
        order_id=order_id,
        merchant_order_id=reference,
        amount_cents=10_000,
        success=False,
    )
    obj["integration_id"] = INTEGRATIONS[integration]
    return obj


def _status(sm: sessionmaker[Session], payment_id: uuid.UUID) -> PaymentStatus:
    with sm() as session:
        status = session.scalar(sa.select(Payment.status).where(Payment.id == payment_id))
    assert status is not None
    return status


def _held_events(sm: sessionmaker[Session], txn_id: int) -> int:
    with sm() as session:
        return (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(PaymobEvent)
                .where(PaymobEvent.dedupe_key == f"rejected_integration:{txn_id}")
            )
            or 0
        )


@pytest.mark.parametrize(("kind", "integration", "accepted"), MATRIX)
def test_callback_integration_per_payment_kind(
    pg_sessionmaker: sessionmaker[Session], kind: str, integration: str, accepted: bool
) -> None:
    payment_id, order_id = _payment(pg_sessionmaker, kind)
    obj = _declined(pg_sessionmaker, payment_id, order_id, integration)
    with pg_sessionmaker.begin() as session:
        BillingService(
            session, FakePaymobClient(SETTINGS), SETTINGS, now=lambda: NOW
        ).apply_transaction_callback(obj)
    if accepted:
        assert _status(pg_sessionmaker, payment_id) is PaymentStatus.failed
        assert _held_events(pg_sessionmaker, obj["id"]) == 0
    else:
        assert _status(pg_sessionmaker, payment_id) is PaymentStatus.pending
        assert _held_events(pg_sessionmaker, obj["id"]) == 1


@pytest.mark.parametrize(("kind", "integration", "accepted"), MATRIX)
def test_inquiry_integration_per_payment_kind(
    pg_sessionmaker: sessionmaker[Session], kind: str, integration: str, accepted: bool
) -> None:
    # The same rule on the reconcile path: an inquiry proves the answer came from Paymob, not
    # which integration took the money.
    payment_id, order_id = _payment(pg_sessionmaker, kind)
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(Payment)
            .where(Payment.id == payment_id)
            .values(next_reconcile_at=NOW - timedelta(minutes=1))
        )
    obj = _declined(pg_sessionmaker, payment_id, order_id, integration)
    inquirer = FakePaymobClient(SETTINGS)
    inquirer.inquiry_response = obj
    with pg_sessionmaker() as session:
        BillingService(session, inquirer, SETTINGS, now=lambda: NOW).reconcile_pending(now=NOW)
    if accepted:
        assert _status(pg_sessionmaker, payment_id) is PaymentStatus.failed
    else:
        assert _status(pg_sessionmaker, payment_id) is PaymentStatus.pending
        with pg_sessionmaker() as session:
            # Held back: no more polling, a person decides.
            assert (
                session.scalar(sa.select(Payment.next_reconcile_at).where(Payment.id == payment_id))
                is None
            )
