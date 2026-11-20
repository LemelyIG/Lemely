"""``card_tokens`` on Phase 02's checkout: saved cards offered to the payer (Phase 06 T4, DV-25).

``BillingService.create_intention_checkout`` gained one keyword. With no tokens the intention is
what it always was; with tokens it carries ``card_tokens`` (at most three, the live ``cit.md``
limit) next to the unchanged card (Normal 3DS) integration, and the tokens are passed to the
client as ``sensitive`` so a Paymob error body that echoes one is scrubbed before it can reach a
log, an exception or the payment row.

Runs on a throwaway Postgres database (``create_all``); skips without a local Postgres.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import sqlalchemy as sa

from lemely.db.billing_repo import BillingService, CheckoutUnavailable
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus
from lemely.io.paymob.client import PaymobClient, PaymobError
from tests.merchant_charge_fixtures import throwaway_database
from tests.paymob_fixtures import (
    CARD_INTEGRATION_ID,
    INTENTION_RESPONSE,
    PAYMOB_SETTINGS,
    FakePaymobClient,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
ITEMS = [{"name": "Plan upgrade (prorated)", "amount": 5_000, "quantity": 1}]
BILLING_DATA = {"first_name": "Sara", "last_name": "Ali", "email": "a@example.com"}
#: ``payments.paymob_order_id`` is unique, so every fake client answers with an order id of its own.
_order_ids = itertools.count(770_001)


def _fresh_order(client: FakePaymobClient) -> None:
    client.intention_response = {**INTENTION_RESPONSE, "intention_order_id": next(_order_ids)}


class _SensitiveFake(FakePaymobClient):
    """Phase 02's fake whose ``create_intention`` accepts, and records, ``sensitive``."""

    def __init__(self) -> None:
        super().__init__()
        _fresh_order(self)
        self.sensitive: list[tuple[str, ...]] = []

    def create_intention(  # type: ignore[override]
        self, body: Mapping[str, object], *, sensitive: Sequence[str] = ()
    ) -> dict[str, Any]:
        self.sensitive.append(tuple(sensitive))
        return super().create_intention(body)


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


def _payment(payer: uuid.UUID) -> Payment:
    payment_id = uuid.uuid4()
    return Payment(
        id=payment_id,
        special_reference=str(payment_id),
        payer_user_id=payer,
        beneficiary_user_id=payer,
        purpose=PaymentPurpose.upgrade_proration,
        amount_minor=5_000,
        currency="EGP",
        status=PaymentStatus.created,
    )


def _checkout(
    sm: sessionmaker[Session],
    client: PaymobClient,
    payer: uuid.UUID,
    **extra: Any,
) -> uuid.UUID:
    payment = _payment(payer)
    with sm() as session:
        BillingService(session, client, PAYMOB_SETTINGS, now=lambda: NOW).create_intention_checkout(
            payment=payment,
            items=ITEMS,
            billing_data=BILLING_DATA,
            subscription_plan_id=None,
            **extra,
        )
    return payment.id


def _normalised(body: dict[str, Any], payment_id: uuid.UUID) -> dict[str, Any]:
    """The body with the per-payment ids blanked, so two payments' bodies can be compared."""
    text = repr(body).replace(str(payment_id), "<id>")
    return {"text": text}


def test_no_tokens_sends_the_body_it_always_sent(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer = seed_user(pg_sessionmaker)
    plain = FakePaymobClient()  # create_intention(body): it has no ``sensitive`` keyword
    _fresh_order(plain)
    with_empty = _SensitiveFake()
    first = _checkout(pg_sessionmaker, plain, payer)
    second = _checkout(pg_sessionmaker, with_empty, payer, card_tokens=())

    (plain_body,) = plain.intentions
    (empty_body,) = with_empty.intentions
    assert "card_tokens" not in plain_body
    assert "card_tokens" not in empty_body
    assert _normalised(plain_body, first) == _normalised(empty_body, second)
    # No tokens, nothing to scrub: the client is called exactly as before.
    assert with_empty.sensitive == [()]


def test_tokens_ride_the_card_integration_intention_in_order(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker)
    client = _SensitiveFake()
    _checkout(pg_sessionmaker, client, payer, card_tokens=["tok_newest", "tok_older"])

    (body,) = client.intentions
    assert body["card_tokens"] == ["tok_newest", "tok_older"]
    assert body["payment_methods"] == [CARD_INTEGRATION_ID]
    assert body["redirection_url"].startswith("https://lemelyig.com/billing/return/")
    assert client.sensitive == [("tok_newest", "tok_older")]


def test_more_than_three_tokens_is_refused_before_any_write(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker)
    client = _SensitiveFake()
    payment = _payment(payer)
    with pytest.raises(ValueError, match="at most 3"), pg_sessionmaker() as session:
        BillingService(session, client, PAYMOB_SETTINGS, now=lambda: NOW).create_intention_checkout(
            payment=payment,
            items=ITEMS,
            billing_data=BILLING_DATA,
            subscription_plan_id=None,
            card_tokens=["t1", "t2", "t3", "t4"],
        )
    assert client.intentions == []
    with pg_sessionmaker() as session:
        assert session.get(Payment, payment.id) is None


def test_three_tokens_are_allowed(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer = seed_user(pg_sessionmaker)
    client = _SensitiveFake()
    _checkout(pg_sessionmaker, client, payer, card_tokens=["t1", "t2", "t3"])
    assert client.intentions[0]["card_tokens"] == ["t1", "t2", "t3"]


def _echoing_client(token: str) -> PaymobClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": f"card token {token} is not usable"})

    return PaymobClient(PAYMOB_SETTINGS, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_a_paymob_400_that_echoes_a_token_is_scrubbed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker)
    token = "tok_secret_card_value"
    client = _echoing_client(token)
    payment = _payment(payer)
    with pytest.raises(CheckoutUnavailable) as caught, pg_sessionmaker() as session:
        BillingService(session, client, PAYMOB_SETTINGS, now=lambda: NOW).create_intention_checkout(
            payment=payment,
            items=ITEMS,
            billing_data=BILLING_DATA,
            subscription_plan_id=None,
            card_tokens=[token],
        )
    cause = caught.value.__cause__
    assert isinstance(cause, PaymobError)
    assert cause.status_code == 400
    assert token not in repr(cause.body)
    assert token not in str(cause)
    with pg_sessionmaker() as session:
        row = session.get(Payment, payment.id)
        assert row is not None
        assert row.status is PaymentStatus.failed  # a definite 4xx
        stored = session.scalar(sa.select(Payment.last_callback).where(Payment.id == payment.id))
        assert token not in repr(stored)


def test_client_forwards_sensitive_to_the_error_scrub() -> None:
    token = "tok_secret_card_value"
    client = _echoing_client(token)
    with pytest.raises(PaymobError) as caught:
        client.create_intention({"amount": 1}, sensitive=(token,))
    assert token not in repr(caught.value.body)
    # Without it the echo would survive: the scrub is what hides it, not the fake.
    with pytest.raises(PaymobError) as unscrubbed:
        client.create_intention({"amount": 1})
    assert token in repr(unscrubbed.value.body)
