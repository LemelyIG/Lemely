"""Plan upgrade through a 3DS checkout that offers saved cards (Phase 06 T4, DV-25, DV-26).

Money safety, in the order the code enforces it: every refusal happens before a payment row is
written or Paymob is called; the checkout is Phase 02's, on the card (Normal 3DS) integration,
never the MOTO one; a ``created`` (abandoned) checkout never blocks a new one but a ``pending``
one does; only the verified callback pays; and a payment whose effect is void at settle time
(the plan ended, the period rolled, the target was already reached, a later upgrade landed) is
turned into credits instead of switching the tier. Every guard here has a mutation proof in the
task report.

Runs on a throwaway Postgres database (``create_all``); skips without a local Postgres.
"""

from __future__ import annotations

import dataclasses
import itertools
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.db import merchant_charge_repo
from lemely.db.billing_repo import (
    BillingService,
    CheckoutUnavailable,
    PhoneRequired,
    paid_handler_for,
)
from lemely.db.merchant_charge_repo import (
    ChargeQuote,
    MerchantChargeError,
    MerchantChargeService,
    SeatsExceedNewTier,
    active_seat_count,
    handle_upgrade_paid,
    offered_card_tokens,
    usable_extra_seats,
)
from lemely.db.models import User
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    SavedCard,
    Subscription,
)
from lemely.db.models.billing_ops import CreditConversionRate
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.team import TeacherMemberStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.usage import GrantKind, UsageGrant
from lemely.io.paymob.client import PaymobError
from tests.merchant_charge_fixtures import (
    link_parent,
    seed_saved_card,
    seed_seat,
    seed_tier,
    seed_user,
    student_with_plan,
    teacher_with_plan,
    throwaway_database,
)
from tests.paymob_fixtures import (
    CARD_INTEGRATION_ID,
    INTENTION_RESPONSE,
    MOTO_INTEGRATION_ID,
    PAYMOB_SETTINGS,
    TEST_CARD_TOKEN_KEY,
    transaction_obj,
)
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    grants_of,
    paymob_settings,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

#: Half the period is left: 30 days from ``T0``.
NOW = T0 + timedelta(days=15)
PERIOD_END = T0 + timedelta(days=30)
_order_ids = itertools.count(990_001)
_txn_ids = itertools.count(5_500_001)


class _CheckoutClient(FakePaymobClient):
    """Subscription fixtures' recording fake whose intention accepts ``sensitive`` and mints ids.

    ``names()`` lists only subscription calls, so an empty list after a settle proves the paid
    handler wrote nothing to Paymob (DV-1).
    """

    def __init__(self, settings: Any = PAYMOB_SETTINGS) -> None:
        super().__init__(settings)
        self.sensitive: list[tuple[str, ...]] = []

    def create_intention(  # type: ignore[override]
        self, body: Mapping[str, object], *, sensitive: Sequence[str] = ()
    ) -> dict[str, Any]:
        self.sensitive.append(tuple(sensitive))
        self.intentions.append(dict(body))
        if self.on_intention is not None:
            self.on_intention(dict(body))
        if isinstance(self.intention_response, Exception):
            raise self.intention_response
        response = dict(self.intention_response)
        response["intention_order_id"] = next(_order_ids)
        response["id"] = f"pi_test_up_{next(_order_ids)}"
        return response


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        with factory.begin() as session:
            session.add(CreditConversionRate(currency="EGP", units_per_minor=Decimal("0.01")))
        yield factory


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _student(sm: sessionmaker[Session], **kwargs: Any) -> dict[str, uuid.UUID]:
    """A student on a 10 000 / 1 000-unit plan with half the period left."""
    return student_with_plan(sm, price=10_000, allowance_units=1_000, **kwargs)


def _target(sm: sessionmaker[Session], **kwargs: Any) -> uuid.UUID:
    """An upgrade target: 20 000 and 3 000 units, so half a period costs 5 000 and adds 1 000."""
    options: dict[str, Any] = {"price_minor": 20_000, "allowance_units": 3_000}
    options.update(kwargs)
    return seed_tier(sm, **options)


def _checkout(
    sm: sessionmaker[Session],
    client: _CheckoutClient,
    scene: Mapping[str, uuid.UUID],
    target: uuid.UUID,
    *,
    actor: uuid.UUID | None = None,
    settings: Any = PAYMOB_SETTINGS,
    now: datetime = NOW,
) -> uuid.UUID:
    with sm() as session:
        result = MerchantChargeService(session, client, settings).start_upgrade_checkout(
            subscription_id=scene["subscription_id"],
            actor_user_id=actor or scene["payer_id"],
            plan_tier_id=target,
            now=now,
        )
    return result.payment_id


def _quote(
    sm: sessionmaker[Session],
    client: _CheckoutClient,
    scene: Mapping[str, uuid.UUID],
    target: uuid.UUID,
    *,
    settings: Any = PAYMOB_SETTINGS,
    now: datetime = NOW,
) -> ChargeQuote:
    with sm() as session:
        return MerchantChargeService(session, client, settings).quote_upgrade(
            subscription_id=scene["subscription_id"],
            actor_user_id=scene["payer_id"],
            plan_tier_id=target,
            now=now,
        )


def _payment(sm: sessionmaker[Session], payment_id: uuid.UUID) -> Payment:
    with sm() as session:
        row = session.get(Payment, payment_id)
        assert row is not None
        return row


def _sub(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, scene["subscription_id"])
        assert row is not None
        return row


def _upgrade_payments(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]) -> int:
    with sm() as session:
        return int(
            session.scalar(
                sa.select(sa.func.count())
                .select_from(Payment)
                .where(
                    Payment.subscription_id == scene["subscription_id"],
                    Payment.purpose == PaymentPurpose.upgrade_proration,
                )
            )
            or 0
        )


def _update_sub(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID], **values: Any) -> None:
    with sm.begin() as session:
        session.execute(
            sa.update(Subscription)
            .where(Subscription.id == scene["subscription_id"])
            .values(**values)
        )


def _set_payment_created_at(
    sm: sessionmaker[Session], payment_id: uuid.UUID, created_at: datetime
) -> None:
    with sm.begin() as session:
        session.execute(
            sa.update(Payment).where(Payment.id == payment_id).values(created_at=created_at)
        )


def _txn(payment: Payment, *, success: bool = True, pending: bool = False) -> dict[str, Any]:
    assert payment.paymob_order_id is not None
    return transaction_obj(
        txn_id=next(_txn_ids),
        order_id=payment.paymob_order_id,
        merchant_order_id=str(payment.id),
        amount_cents=payment.amount_minor,
        success=success,
        pending=pending,
    )


def _deliver(sm: sessionmaker[Session], obj: dict[str, Any], *, at: datetime = NOW) -> None:
    with sm.begin() as session:
        BillingService(
            session, _CheckoutClient(), PAYMOB_SETTINGS, now=lambda: at
        ).apply_transaction_callback(obj)


def _pay(sm: sessionmaker[Session], payment_id: uuid.UUID, *, at: datetime = NOW) -> None:
    _deliver(sm, _txn(_payment(sm, payment_id)), at=at)


def _grant(sm: sessionmaker[Session], owner: uuid.UUID, key: str) -> UsageGrant | None:
    return next((g for g in grants_of(sm, owner) if g.idempotency_key == key), None)


def _credited_notices(sm: sessionmaker[Session], recipient: uuid.UUID) -> int:
    with sm() as session:
        rows = session.scalars(
            sa.select(EmailOutbox).where(EmailOutbox.recipient_user_id == recipient)
        ).all()
    return sum(1 for row in rows if row.context.get("notice") == "credited")


def _refused(
    sm: sessionmaker[Session],
    client: _CheckoutClient,
    scene: Mapping[str, uuid.UUID],
    target: uuid.UUID,
    code: str,
    **kwargs: Any,
) -> MerchantChargeError:
    """The checkout is refused with ``code``, leaving no payment row and no Paymob call."""
    before = _upgrade_payments(sm, scene)
    with pytest.raises(MerchantChargeError) as caught:
        _checkout(sm, client, scene, target, **kwargs)
    assert caught.value.code == code
    assert _upgrade_payments(sm, scene) == before
    assert client.intentions == []
    return caught.value


# ---------------------------------------------------------------------------
# The checkout.
# ---------------------------------------------------------------------------


def test_the_checkout_records_the_payment_and_opens_a_card_integration_intention(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    client = _CheckoutClient()

    payment_id = _checkout(sm, client, scene, target)

    payment = _payment(sm, payment_id)
    assert payment.purpose is PaymentPurpose.upgrade_proration
    assert payment.status is PaymentStatus.created
    assert payment.amount_minor == 5_000
    assert payment.currency == "EGP"
    assert payment.plan_tier_id == target
    assert payment.subscription_id == scene["subscription_id"]
    assert payment.payer_user_id == scene["payer_id"]
    assert payment.beneficiary_user_id == scene["user_id"]
    assert payment.dedupe_key is None
    assert payment.created_at == NOW  # the injected clock, which the settle-time rules compare
    (body,) = client.intentions
    assert body["payment_methods"] == [CARD_INTEGRATION_ID]
    assert MOTO_INTEGRATION_ID not in body["payment_methods"]
    assert body["items"] == [{"name": "Plan upgrade (prorated)", "amount": 5_000, "quantity": 1}]
    assert body["amount"] == 5_000
    assert body["redirection_url"] == f"https://lemelyig.com/billing/return/{payment_id}"
    assert body["special_reference"] == str(payment_id)
    assert "subscription_plan_id" not in body
    assert _sub(sm, scene).plan_tier_id == scene["tier_id"]  # nothing switched yet


def test_the_checkout_offers_the_payers_newest_cards_decrypted(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm, card=False)
    for index in range(4):
        seed_saved_card(
            sm, scene["payer_id"], token=f"tok_c{index}", created_at=T0 + timedelta(days=index)
        )
    target = _target(sm)
    client = _CheckoutClient()

    _checkout(sm, client, scene, target)

    (body,) = client.intentions
    assert body["card_tokens"] == ["tok_c3", "tok_c2", "tok_c1"]  # newest first, at most three
    assert body["payment_methods"] == [CARD_INTEGRATION_ID]
    assert client.sensitive == [("tok_c3", "tok_c2", "tok_c1")]


def test_a_card_whose_ciphertext_was_swapped_is_skipped_not_fatal(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm, card=False)
    stranger = seed_user(sm, Role.student)
    foreign_card = seed_saved_card(sm, stranger, token="tok_foreign")
    seed_saved_card(sm, scene["payer_id"], token="tok_own_old", created_at=T0)
    swapped = seed_saved_card(
        sm, scene["payer_id"], token="tok_own_new", created_at=T0 + timedelta(days=1)
    )
    with sm.begin() as session:
        foreign = session.get(SavedCard, foreign_card)
        row = session.get(SavedCard, swapped)
        assert foreign is not None and row is not None
        row.token = foreign.token  # another user's ciphertext: it will not open for this owner
    target = _target(sm)
    client = _CheckoutClient()

    with capture_logs() as logs:
        _checkout(sm, client, scene, target)

    (body,) = client.intentions
    assert body["card_tokens"] == ["tok_own_old"]
    skipped = [log for log in logs if log["event"] == "saved_card_not_offered"]
    assert [log["card_id"] for log in skipped] == [str(swapped)]
    assert "tok_foreign" not in repr(logs)


def test_a_payer_with_no_saved_card_still_gets_a_plain_checkout(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm, card=False)
    target = _target(sm)
    client = _CheckoutClient()

    payment_id = _checkout(sm, client, scene, target)

    (body,) = client.intentions
    assert "card_tokens" not in body
    assert client.sensitive == [()]
    assert _payment(sm, payment_id).status is PaymentStatus.created


def test_a_payer_without_a_card_token_key_gets_a_plain_checkout(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    settings = paymob_settings(card_token_key=None)
    client = _CheckoutClient(settings)

    _checkout(sm, client, scene, target, settings=settings)

    assert "card_tokens" not in client.intentions[0]


def test_offered_card_tokens_reads_at_most_three_cards(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    payer = seed_user(sm, Role.student)
    for index in range(5):
        seed_saved_card(sm, payer, token=f"tok_{index}", created_at=T0 + timedelta(days=index))
    with sm() as session:
        service = BillingService(session, _CheckoutClient(), PAYMOB_SETTINGS)
        assert offered_card_tokens(service, session, payer) == ["tok_4", "tok_3", "tok_2"]
    assert TEST_CARD_TOKEN_KEY  # the key the fixtures encrypt under


# ---------------------------------------------------------------------------
# Refusals: no payment row, no Paymob call.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "target_kwargs"),
    [
        ("cheaper", {"price_minor": 5_000}),
        ("same price", {"price_minor": 10_000}),
        ("other interval", {"interval": PlanInterval.yearly}),
        ("other audience", {"audience": PlanAudience.teacher}),
    ],
)
def test_a_target_that_is_not_an_upgrade_is_refused(
    pg_sessionmaker: sessionmaker[Session], label: str, target_kwargs: dict[str, Any]
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm, **target_kwargs)
    _refused(sm, _CheckoutClient(), scene, target, "not_an_upgrade")
    assert label


def test_an_inactive_or_unknown_target_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    inactive = _target(sm, is_active=False)
    _refused(sm, _CheckoutClient(), scene, inactive, "tier_not_found")
    _refused(sm, _CheckoutClient(), scene, uuid.uuid4(), "tier_not_found")


def test_a_past_due_plan_cannot_start_an_upgrade(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    _update_sub(sm, scene, status=SubscriptionStatus.past_due)
    _refused(sm, _CheckoutClient(), scene, _target(sm), "subscription_not_active")


def test_a_scheduled_downgrade_or_cancel_blocks_an_upgrade(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    target = _target(sm)
    pending = _student(sm)
    _update_sub(sm, pending, pending_plan_tier_id=seed_tier(sm, price_minor=5_000))
    _refused(sm, _CheckoutClient(), pending, target, "plan_change_pending")
    cancelling = _student(sm)
    _update_sub(sm, cancelling, cancel_at_period_end=True)
    _refused(sm, _CheckoutClient(), cancelling, target, "plan_change_pending")


def test_with_the_fixed_amount_fallback_an_upgrade_says_what_to_do_instead(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    settings = paymob_settings(subscription_amount_updatable=False)
    error = _refused(
        sm, _CheckoutClient(settings), scene, _target(sm), "upgrade_unavailable", settings=settings
    )
    assert error.detail == {"next": "cancel_and_resubscribe"}
    with pytest.raises(MerchantChargeError) as quote:
        _quote(sm, _CheckoutClient(settings), scene, _target(sm), settings=settings)
    assert quote.value.code == "upgrade_unavailable"
    assert quote.value.detail == {"next": "cancel_and_resubscribe"}


def test_a_plan_with_no_linked_paymob_subscription_cannot_be_upgraded(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    _update_sub(sm, scene, paymob_subscription_id=None)
    _refused(sm, _CheckoutClient(), scene, _target(sm), "upgrade_unavailable")


def test_an_upgrade_in_the_last_instant_of_the_period_is_refused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    _refused(sm, _CheckoutClient(), scene, _target(sm), "period_ending", now=PERIOD_END)


def test_a_payer_without_a_phone_is_refused_before_any_write(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    parent = seed_user(sm, Role.parent, phone=None)
    scene = _student(sm, payer_id=parent)
    link_parent(sm, parent_id=parent, child_id=scene["user_id"])
    client = _CheckoutClient()
    with pytest.raises(PhoneRequired):
        _checkout(sm, client, scene, _target(sm))
    assert _upgrade_payments(sm, scene) == 0
    assert client.intentions == []


def test_an_upgrade_with_checkout_not_configured_leaves_nothing_behind(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    settings = paymob_settings(secret_key=None)
    client = _CheckoutClient(settings)
    with pytest.raises(CheckoutUnavailable):
        _checkout(sm, client, scene, _target(sm), settings=settings)
    assert _upgrade_payments(sm, scene) == 0
    assert client.intentions == []


def test_nobody_but_the_payer_can_start_or_quote_an_upgrade(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    parent = seed_user(sm, Role.parent)
    linked = _student(sm, payer_id=parent)
    link_parent(sm, parent_id=parent, child_id=linked["user_id"])
    unlinked_parent = seed_user(sm, Role.parent)
    unlinked = _student(sm, payer_id=unlinked_parent)  # the link was never made, or was removed
    target = _target(sm)
    stranger = seed_user(sm, Role.student)
    missing = {**linked, "subscription_id": uuid.uuid4()}

    attempts = [
        (linked, stranger),
        (linked, linked["user_id"]),  # the beneficiary child
        (unlinked, unlinked_parent),  # the payer, but no longer linked to the child
        (missing, parent),  # an unknown id
    ]
    errors: list[MerchantChargeError] = []
    for scene, actor in attempts:
        client = _CheckoutClient()
        with pytest.raises(MerchantChargeError) as caught:
            _checkout(sm, client, scene, target, actor=actor)
        errors.append(caught.value)
        assert client.intentions == []
        with sm() as session, pytest.raises(MerchantChargeError) as quoted:
            MerchantChargeService(session, client, PAYMOB_SETTINGS).quote_upgrade(
                subscription_id=scene["subscription_id"],
                actor_user_id=actor,
                plan_tier_id=target,
                now=NOW,
            )
        assert quoted.value.code == "not_found"
    assert {(e.code, str(e)) for e in errors} == {("not_found", "Subscription not found")}
    assert _upgrade_payments(sm, linked) == 0
    assert _upgrade_payments(sm, unlinked) == 0


def test_a_linked_parent_who_pays_can_upgrade_the_childs_plan(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    parent = seed_user(sm, Role.parent)
    scene = _student(sm, payer_id=parent)
    link_parent(sm, parent_id=parent, child_id=scene["user_id"])
    payment_id = _checkout(sm, _CheckoutClient(), scene, _target(sm))
    payment = _payment(sm, payment_id)
    assert (payment.payer_user_id, payment.beneficiary_user_id) == (parent, scene["user_id"])


# ---------------------------------------------------------------------------
# Unknown and refused outcomes at creation (R20b).
# ---------------------------------------------------------------------------


def test_an_unknown_outcome_leaves_the_payment_created_and_allows_another_checkout(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    client = _CheckoutClient()
    client.intention_response = PaymobError("timed out", timeout=True)

    with pytest.raises(CheckoutUnavailable):
        _checkout(sm, client, scene, target)

    with sm() as session:
        [row] = session.scalars(
            sa.select(Payment).where(
                Payment.subscription_id == scene["subscription_id"],
                Payment.purpose == PaymentPurpose.upgrade_proration,
            )
        ).all()
    assert row.status is PaymentStatus.created  # reconcile settles it, never failed here
    assert row.next_reconcile_at is not None
    client.intention_response = dict(INTENTION_RESPONSE)
    second = _checkout(sm, client, scene, target)  # an unknown one never blocks a new checkout
    assert _payment(sm, second).status is PaymentStatus.created
    assert _upgrade_payments(sm, scene) == 2


def test_a_definite_refusal_fails_the_payment(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    client = _CheckoutClient()
    client.intention_response = PaymobError("bad request", status_code=400)

    with pytest.raises(CheckoutUnavailable):
        _checkout(sm, client, scene, _target(sm))

    with sm() as session:
        [row] = session.scalars(
            sa.select(Payment).where(
                Payment.subscription_id == scene["subscription_id"],
                Payment.purpose == PaymentPurpose.upgrade_proration,
            )
        ).all()
    assert row.status is PaymentStatus.failed


# ---------------------------------------------------------------------------
# One open checkout (DV-26): created never blocks, pending does.
# ---------------------------------------------------------------------------


def test_an_abandoned_created_checkout_does_not_block_a_new_one(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    client = _CheckoutClient()
    first = _checkout(sm, client, scene, target)
    assert _payment(sm, first).status is PaymentStatus.created

    second = _checkout(sm, client, scene, target)

    assert second != first
    assert _upgrade_payments(sm, scene) == 2


def test_a_pending_checkout_blocks_a_new_one(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    client = _CheckoutClient()
    first = _checkout(sm, client, scene, target)
    _deliver(sm, _txn(_payment(sm, first), success=False, pending=True))
    assert _payment(sm, first).status is PaymentStatus.pending

    error = _refused(sm, _CheckoutClient(), scene, target, "charge_in_flight")

    assert str(error)
    assert _upgrade_payments(sm, scene) == 1


# ---------------------------------------------------------------------------
# The paid handler.
# ---------------------------------------------------------------------------


def test_the_handler_is_registered_for_upgrades() -> None:
    assert paid_handler_for(PaymentPurpose.upgrade_proration) is handle_upgrade_paid


def test_a_paid_upgrade_switches_the_tier_once_through_the_real_callback_path(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    client = _CheckoutClient()
    payment_id = _checkout(sm, client, scene, target)
    before = _sub(sm, scene)
    obj = _txn(_payment(sm, payment_id))

    _deliver(sm, obj)
    # Paymob retries a callback. There is deliberately no reconcile leg: ``reconcile_pending``
    # never selects a ``paid`` payment, so it would pass whatever the handler does. Exactly-once
    # rests on the two callbacks, the ``upgrade:{id}`` grant key and ``version`` bumped once.
    _deliver(sm, obj)

    after = _sub(sm, scene)
    assert after.plan_tier_id == target
    assert after.terms_version == 1
    assert after.pending_terms_version is None
    assert after.version == before.version + 1  # bumped once
    assert after.paymob_amount_minor == before.paymob_amount_minor  # stamp unchanged (DV-1)
    payment = _payment(sm, payment_id)
    assert payment.status is PaymentStatus.paid
    assert payment.paid_at == NOW
    assert payment.grant_units is None  # bought the plan, not credits
    allowance = [g for g in grants_of(sm, scene["user_id"]) if g.kind is GrantKind.period_allowance]
    assert len(allowance) == 1
    grant = allowance[0]
    assert grant.idempotency_key == f"upgrade:{payment_id}"
    assert grant.units == 1_000  # (3000 - 1000) x 1/2
    assert grant.visible is False
    assert grant.effective_at == NOW
    assert grant.expires_at == PERIOD_END
    assert grant.subscription_period_id == scene["period_id"]
    assert grant.payment_id == payment_id
    assert client.names() == []  # no Paymob write anywhere
    assert _credited_notices(sm, scene["payer_id"]) == 0


def test_a_later_upgrade_to_the_same_target_is_credited_not_applied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    client = _CheckoutClient()
    first = _checkout(sm, client, scene, target)
    second = _checkout(sm, client, scene, target)

    _pay(sm, second, at=NOW + timedelta(minutes=1))
    with capture_logs() as logs:
        _pay(sm, first, at=NOW + timedelta(minutes=2))  # the stale quote

    assert _sub(sm, scene).plan_tier_id == target
    assert _grant(sm, scene["user_id"], f"upgrade:{first}") is None
    assert _grant(sm, scene["user_id"], f"upgrade:{second}") is not None
    credited = _grant(sm, scene["user_id"], f"credited:{first}")
    assert credited is not None and credited.visible is True
    assert _payment(sm, first).grant_units == credited.units == 50
    [event] = [log for log in logs if log["event"] == "merchant_charge_credited"]
    assert event["reason"] == "not_an_upgrade_now"
    assert _credited_notices(sm, scene["payer_id"]) == 1


def test_an_upgrade_priced_before_another_one_landed_is_credited_never_applied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    x_tier = _target(sm, price_minor=20_000)
    y_tier = _target(sm, price_minor=30_000, allowance_units=5_000)
    client = _CheckoutClient()
    to_x = _checkout(sm, client, scene, x_tier)
    to_y = _checkout(sm, client, scene, y_tier, now=NOW + timedelta(minutes=1))

    _pay(sm, to_x, at=NOW + timedelta(minutes=2))
    assert _sub(sm, scene).plan_tier_id == x_tier
    with capture_logs() as logs:
        _pay(sm, to_y, at=NOW + timedelta(minutes=3))

    # Y was priced as old -> Y (10 000 difference); applying it after X would overcharge X -> Y.
    assert _sub(sm, scene).plan_tier_id == x_tier
    assert _grant(sm, scene["user_id"], f"upgrade:{to_y}") is None
    assert _grant(sm, scene["user_id"], f"credited:{to_y}") is not None
    [event] = [log for log in logs if log["event"] == "merchant_charge_credited"]
    assert event["reason"] == "superseded"


def test_a_checkout_that_outlived_its_period_is_credited(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    payment_id = _checkout(sm, _CheckoutClient(), scene, target)
    renewed = NOW + timedelta(days=1)
    _update_sub(
        sm,
        scene,
        current_period_start=renewed,
        current_period_end=renewed + timedelta(days=30),
    )

    with capture_logs() as logs:
        _pay(sm, payment_id, at=NOW + timedelta(days=2))

    assert _sub(sm, scene).plan_tier_id == scene["tier_id"]
    assert _grant(sm, scene["user_id"], f"upgrade:{payment_id}") is None
    assert _grant(sm, scene["user_id"], f"credited:{payment_id}") is not None
    [event] = [log for log in logs if log["event"] == "merchant_charge_credited"]
    assert event["reason"] == "period_rolled"


def test_a_checkout_paid_after_the_plan_ended_becomes_credits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    payment_id = _checkout(sm, _CheckoutClient(), scene, target)
    _update_sub(sm, scene, status=SubscriptionStatus.expired)

    with capture_logs() as logs:
        _pay(sm, payment_id, at=NOW + timedelta(minutes=5))

    assert _sub(sm, scene).plan_tier_id == scene["tier_id"]
    credited = _grant(sm, scene["user_id"], f"credited:{payment_id}")
    assert credited is not None
    assert (credited.kind, credited.visible, credited.units) == (GrantKind.credit_pack, True, 50)
    assert _payment(sm, payment_id).grant_units == 50
    assert _payment(sm, payment_id).status is PaymentStatus.paid
    assert _credited_notices(sm, scene["payer_id"]) == 1
    assert [log["event"] for log in logs if log.get("alert")] == []  # an automatic, decided outcome
    [event] = [log for log in logs if log["event"] == "merchant_charge_credited"]
    assert event["reason"] == "plan_ended"


def test_without_a_credit_rate_the_payment_stays_paid_and_an_alert_asks_for_a_refund(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    payment_id = _checkout(sm, _CheckoutClient(), scene, target)
    _update_sub(sm, scene, status=SubscriptionStatus.expired)
    with sm.begin() as session:
        session.execute(sa.delete(CreditConversionRate))
    try:
        with capture_logs() as logs:
            _pay(sm, payment_id, at=NOW + timedelta(minutes=5))
    finally:
        with sm.begin() as session:
            session.add(CreditConversionRate(currency="EGP", units_per_minor=Decimal("0.01")))

    assert _payment(sm, payment_id).status is PaymentStatus.paid  # the callback was not rejected
    assert _grant(sm, scene["user_id"], f"credited:{payment_id}") is None
    [alert] = [log for log in logs if log.get("alert")]
    assert alert["event"] == "merchant_charge_unconvertible"
    assert alert["reason"] == "no_rate"


def test_a_checkout_paid_at_the_period_end_switches_the_tier_without_a_grant(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    payment_id = _checkout(sm, _CheckoutClient(), scene, target)

    _pay(sm, payment_id, at=PERIOD_END)

    assert _sub(sm, scene).plan_tier_id == target
    assert _grant(sm, scene["user_id"], f"upgrade:{payment_id}") is None


def test_an_upgrade_that_adds_no_allowance_grants_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm, allowance_units=1_000)
    payment_id = _checkout(sm, _CheckoutClient(), scene, target)
    _pay(sm, payment_id)
    assert _sub(sm, scene).plan_tier_id == target
    assert _grant(sm, scene["user_id"], f"upgrade:{payment_id}") is None


def test_the_handler_refuses_a_payment_with_no_paid_at(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    payment_id = _checkout(sm, _CheckoutClient(), scene, _target(sm))
    with sm() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        with pytest.raises(RuntimeError, match="paid_at"):
            merchant_charge_repo.on_upgrade_paid(session, payment)


def test_a_pending_terms_move_is_replaced_by_the_targets_terms(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    payment_id = _checkout(sm, _CheckoutClient(), scene, target)
    # A notice for the old tier's terms is scheduled; the upgrade supersedes it.
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO plan_tier_terms (plan_tier_id, terms_version, price_minor, "
                "extra_seat_price_minor, allowance_units, included_seats, seat_allowance_units) "
                "SELECT plan_tier_id, 2, price_minor + 100, extra_seat_price_minor, "
                "allowance_units, included_seats, seat_allowance_units FROM plan_tier_terms "
                "WHERE plan_tier_id = :tier AND terms_version = 1"
            ),
            {"tier": scene["tier_id"]},
        )
    _update_sub(
        sm,
        scene,
        pending_terms_version=2,
        pending_terms_effective_at=PERIOD_END,
    )

    _pay(sm, payment_id)

    after = _sub(sm, scene)
    assert after.plan_tier_id == target
    assert (after.terms_version, after.pending_terms_version) == (1, None)
    assert after.pending_terms_effective_at is None


def test_the_price_paid_is_the_billed_terms_not_the_tiers_current_price(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm)
    with sm.begin() as session:  # the admin raised the old tier's price; this subscriber keeps v1
        session.execute(
            sa.text(
                "INSERT INTO plan_tier_terms (plan_tier_id, terms_version, price_minor, "
                "extra_seat_price_minor, allowance_units, included_seats, seat_allowance_units) "
                "SELECT plan_tier_id, 2, 16000, extra_seat_price_minor, allowance_units, "
                "included_seats, seat_allowance_units FROM plan_tier_terms "
                "WHERE plan_tier_id = :tier AND terms_version = 1"
            ),
            {"tier": scene["tier_id"]},
        )
        session.execute(
            sa.text("UPDATE plan_tiers SET price_minor = 16000, terms_version = 2 WHERE id = :t"),
            {"t": scene["tier_id"]},
        )
    quote = _quote(sm, _CheckoutClient(), scene, target)
    assert quote.amount_minor == 5_000  # (20 000 - the 10 000 they pay) x 1/2


# ---------------------------------------------------------------------------
# Teacher plans (UD-5, DV-8).
# ---------------------------------------------------------------------------


def _seat_teacher(
    sm: sessionmaker[Session], teacher_id: uuid.UUID, *, active: int, leaving: int = 0
) -> None:
    for _ in range(active):
        seed_seat(sm, teacher_id=teacher_id, student_id=seed_user(sm, Role.student))
    for _ in range(leaving):
        seed_seat(
            sm,
            teacher_id=teacher_id,
            student_id=seed_user(sm, Role.student),
            status=TeacherMemberStatus.leaving,
        )


def _teacher_target(sm: sessionmaker[Session], *, included: int) -> uuid.UUID:
    return seed_tier(
        sm,
        audience=PlanAudience.teacher,
        price_minor=40_000,
        allowance_units=2_000,
        included_seats=included,
        extra_seat_price_minor=2_000,
    )


def test_more_active_seats_than_the_target_seats_refuses_the_upgrade(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = teacher_with_plan(sm, included=3)
    _seat_teacher(sm, scene["teacher_id"], active=3)
    target = _teacher_target(sm, included=2)
    client = _CheckoutClient()
    error = _refused(sm, client, scene, target, "seats_exceed_new_tier")
    assert isinstance(error, SeatsExceedNewTier)
    assert (error.in_use, error.capacity) == (3, 2)
    assert error.detail == {"in_use": 3, "capacity": 2}


def test_a_leaving_seat_does_not_count_against_the_target(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = teacher_with_plan(sm, included=3)
    _seat_teacher(sm, scene["teacher_id"], active=2, leaving=1)
    target = _teacher_target(sm, included=2)
    payment_id = _checkout(sm, _CheckoutClient(), scene, target)
    assert _payment(sm, payment_id).status is PaymentStatus.created
    with sm() as session:
        assert active_seat_count(session, scene["teacher_id"]) == 2


def test_a_scheduled_seat_reduction_lowers_the_usable_extra_seats(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    target = _teacher_target(sm, included=2)
    held = teacher_with_plan(sm, included=2, extra=1, pending=0, paymob_amount=32_000)
    _seat_teacher(sm, held["teacher_id"], active=3)
    error = _refused(sm, _CheckoutClient(), held, target, "seats_exceed_new_tier")
    assert isinstance(error, SeatsExceedNewTier)
    assert (error.in_use, error.capacity) == (3, 2)

    kept = teacher_with_plan(sm, included=2, extra=1, pending=None, paymob_amount=32_000)
    _seat_teacher(sm, kept["teacher_id"], active=3)
    payment_id = _checkout(sm, _CheckoutClient(), kept, target)  # the extra seat still seats one
    assert _payment(sm, payment_id).status is PaymentStatus.created
    with sm() as session:
        sub = session.get(Subscription, kept["subscription_id"])
        assert sub is not None and usable_extra_seats(sub) == 1


def test_usable_extra_seats_follows_the_pending_reduction() -> None:
    def sub(extra: int, pending: int | None) -> Subscription:
        return Subscription(extra_seats=extra, pending_extra_seats=pending)

    assert usable_extra_seats(sub(3, None)) == 3
    assert usable_extra_seats(sub(3, 1)) == 1
    assert usable_extra_seats(sub(1, 5)) == 1  # a pending count never adds seats
    assert usable_extra_seats(sub(0, None)) == 0


# ---------------------------------------------------------------------------
# The quote.
# ---------------------------------------------------------------------------


def test_the_quote_matches_the_checkout_needs_no_card_and_writes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    parent = seed_user(sm, Role.parent, phone=None)  # no phone, and no saved card below
    scene = _student(sm, payer_id=parent, card=False)
    link_parent(sm, parent_id=parent, child_id=scene["user_id"])
    target = _target(sm)
    client = _CheckoutClient()

    quote = _quote(sm, client, scene, target)

    assert quote == ChargeQuote(
        amount_minor=5_000, currency="EGP", allowance_units=1_000, period_end=PERIOD_END
    )
    assert _upgrade_payments(sm, scene) == 0
    assert client.intentions == [] and client.names() == []

    # The same plan, a payer who can check out: the checkout bills exactly what was quoted.
    with sm.begin() as session:
        session.execute(sa.update(User).where(User.id == parent).values(phone="+201234567890"))
    payment_id = _checkout(sm, client, scene, target)
    assert _payment(sm, payment_id).amount_minor == quote.amount_minor
    _pay(sm, payment_id)
    grant = _grant(sm, scene["user_id"], f"upgrade:{payment_id}")
    assert grant is not None
    assert grant.units == quote.allowance_units
    assert grant.expires_at == quote.period_end


def test_a_quote_cannot_be_edited() -> None:
    quote = ChargeQuote(amount_minor=1, currency="EGP", allowance_units=0, period_end=PERIOD_END)
    with pytest.raises(dataclasses.FrozenInstanceError):
        quote.amount_minor = 2  # type: ignore[misc]


def _publish_terms(
    sm: sessionmaker[Session], tier_id: uuid.UUID, version: int, price_minor: int
) -> None:
    """An admin publishes the next terms version of ``tier_id`` at ``price_minor``."""
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO plan_tier_terms (plan_tier_id, terms_version, price_minor, "
                "extra_seat_price_minor, allowance_units, included_seats, seat_allowance_units) "
                "SELECT plan_tier_id, :v, :p, extra_seat_price_minor, allowance_units, "
                "included_seats, seat_allowance_units FROM plan_tier_terms "
                "WHERE plan_tier_id = :tier AND terms_version = 1"
            ),
            {"tier": tier_id, "v": version, "p": price_minor},
        )
        session.execute(
            sa.text("UPDATE plan_tiers SET price_minor = :p, terms_version = :v WHERE id = :t"),
            {"t": tier_id, "v": version, "p": price_minor},
        )


def test_a_credited_payment_does_not_supersede_a_correctly_priced_upgrade(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    x_tier = _target(sm, price_minor=20_000)
    y_tier = _target(sm, price_minor=30_000, allowance_units=5_000)
    client = _CheckoutClient()
    a = _checkout(sm, client, scene, x_tier)
    b = _checkout(sm, client, scene, x_tier, now=NOW + timedelta(minutes=1))
    _pay(sm, a, at=NOW + timedelta(minutes=2))  # applied: the tier is X
    c = _checkout(sm, client, scene, y_tier, now=NOW + timedelta(minutes=3))  # priced X -> Y
    with capture_logs() as logs:
        _pay(sm, b, at=NOW + timedelta(minutes=4))  # stale same-target tab: credited, moves nothing
        _pay(sm, c, at=NOW + timedelta(minutes=5))

    reasons = [log["reason"] for log in logs if log["event"] == "merchant_charge_credited"]
    assert reasons == ["not_an_upgrade_now"]  # only B; C was priced correctly and is applied
    assert _sub(sm, scene).plan_tier_id == y_tier
    assert _grant(sm, scene["user_id"], f"upgrade:{c}") is not None
    assert _grant(sm, scene["user_id"], f"credited:{c}") is None
    assert _grant(sm, scene["user_id"], f"credited:{b}") is not None


def test_an_upgrade_credited_for_a_rolled_period_does_not_void_a_later_one(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    x_tier = _target(sm, price_minor=20_000)
    old_checkout = _checkout(sm, _CheckoutClient(), scene, x_tier)
    renewed = NOW + timedelta(days=1)
    _update_sub(
        sm, scene, current_period_start=renewed, current_period_end=renewed + timedelta(days=30)
    )
    fresh_now = renewed + timedelta(days=15)
    fresh = _checkout(sm, _CheckoutClient(), scene, x_tier, now=fresh_now)
    _pay(sm, old_checkout, at=fresh_now + timedelta(minutes=1))  # credited: period_rolled
    with capture_logs() as logs:
        _pay(sm, fresh, at=fresh_now + timedelta(minutes=2))

    assert not [log for log in logs if log["event"] == "merchant_charge_credited"]
    assert _sub(sm, scene).plan_tier_id == x_tier
    assert _grant(sm, scene["user_id"], f"upgrade:{fresh}") is not None


def test_a_target_price_raised_between_checkout_and_payment_is_credited_not_applied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _student(sm)
    target = _target(sm, price_minor=20_000)
    payment_id = _checkout(sm, _CheckoutClient(), scene, target)  # charged 5 000
    _publish_terms(sm, target, 2, 40_000)

    with capture_logs() as logs:
        _pay(sm, payment_id)

    after = _sub(sm, scene)
    assert (after.plan_tier_id, after.terms_version) == (scene["tier_id"], 1)  # never moved to v2
    assert _grant(sm, scene["user_id"], f"upgrade:{payment_id}") is None
    credited = _grant(sm, scene["user_id"], f"credited:{payment_id}")
    assert credited is not None
    [event] = [log for log in logs if log["event"] == "merchant_charge_credited"]
    assert event["reason"] == "superseded"
