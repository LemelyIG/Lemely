"""Merchant-charge routes: upgrade, extra seats, seat reduction, auto top-up (Phase 06 T9).

Money and access safety, in the order the routes enforce it: only the person who pays acts on a
plan (a beneficiary, a stranger, an unlinked parent and a teacher's assistant all get the one
identical 404 and no Paymob call); the three seat routes are teacher-only and the acting-teacher
header is never read; both checkout POSTs share the payer's checkout budget; a refusal happens
before any row or Paymob call, an unknown Paymob outcome keeps the row ``created`` (503, retry
allowed) and a definite refusal fails it; the wire shapes are the ones the built frontend reads
(``web/src/lib/billingTypes.ts``). Every guard here has a mutation proof in the task report.

Runs on a throwaway Postgres database (``create_all``); skips without a local Postgres.
"""

from __future__ import annotations

import itertools
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from lemely.db.billing_repo import BillingService
from lemely.db.merchant_charge_repo import MerchantChargeError
from lemely.db.models.billing import (
    AutoTopupSettings,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    Subscription,
)
from lemely.db.models.billing_ops import CreditConversionRate
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.io.paymob.client import PaymobError
from lemely.runtime.config import PaymobSettings, Settings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_settings
from lemely.web.deps_billing import (
    get_billing_sessionmaker,
    get_checkout_limiter,
    get_merchant_charge_deps,
)
from lemely.web.merchant_charge_deps import MerchantChargeDeps
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.routers import billing as billing_router
from lemely.web.routers.billing import charge_error
from tests.merchant_charge_fixtures import (
    link_parent,
    seed_pack,
    seed_payment_row,
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
    PAYMOB_SETTINGS,
    transaction_obj,
)
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    ensure_billing_settings,
    paymob_settings,
)
from tests.team_db import add_assistant, emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

BILLING = billing_router.router.prefix
ACTING = "X-Lemely-Acting-Teacher"
#: Half the period is left: 30 days from ``T0``.
NOW = T0 + timedelta(days=15)
_order_ids = itertools.count(770_001)
_txn_ids = itertools.count(6_600_001)


class _CheckoutClient(FakePaymobClient):
    """The subscription fixtures' recording fake whose intention accepts ``sensitive``."""

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
        response["id"] = f"pi_test_route_{next(_order_ids)}"
        return response


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def pg_sessionmaker(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    ensure_billing_settings(_database)
    with _database.begin() as session:
        session.execute(sa.delete(CreditConversionRate))
        session.add(CreditConversionRate(currency="EGP", units_per_minor=Decimal("0.01")))
    yield from emptied_after(_database)


class Harness:
    """An app over the throwaway database, a scripted Paymob and one signed-in user at a time."""

    def __init__(
        self,
        sm: sessionmaker[Session],
        *,
        settings: PaymobSettings | None = None,
        checkout_limit: int = 100,
    ) -> None:
        self.sm = sm
        self.fake = _CheckoutClient()
        self.paymob = settings or paymob_settings()
        self.app = create_app()
        self.full = Settings().model_copy(update={"paymob": self.paymob})
        self.app.dependency_overrides[get_settings] = lambda: self.full
        self.app.dependency_overrides[get_billing_sessionmaker] = lambda: sm
        deps = MerchantChargeDeps(sm, self.fake, self.paymob)
        self.app.dependency_overrides[get_merchant_charge_deps] = lambda: deps
        self.limiter = SlidingWindowLimiter(
            limit=checkout_limit, window_seconds=60, clock=time.monotonic
        )
        self.app.dependency_overrides[get_checkout_limiter] = lambda: self.limiter
        self.app.dependency_overrides[billing_router.get_billing_clock] = lambda: lambda: NOW
        self.http = TestClient(self.app)

    def as_user(self, user_id: uuid.UUID, role: Role) -> TestClient:
        self.app.dependency_overrides[get_auth_context] = lambda: AuthContext(
            user_id=str(user_id), role=role.value
        )
        return self.http


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _error(response: Any) -> str:
    return str(response.json()["detail"]["error"])


def _tier(sm: sessionmaker[Session], **kwargs: Any) -> uuid.UUID:
    """An upgrade target for a 10 000 student plan: half a period costs 5 000, adds 1 000."""
    options: dict[str, Any] = {"price_minor": 20_000, "allowance_units": 3_000}
    options.update(kwargs)
    return seed_tier(sm, **options)


def _payments(sm: sessionmaker[Session], purpose: PaymentPurpose) -> list[Payment]:
    with sm() as session:
        return list(session.scalars(sa.select(Payment).where(Payment.purpose == purpose)).all())


def _payment(sm: sessionmaker[Session], payment_id: str | uuid.UUID) -> Payment:
    with sm() as session:
        row = session.get(Payment, uuid.UUID(str(payment_id)))
        assert row is not None
        return row


def _upgrade_url(scene: Mapping[str, uuid.UUID], tail: str = "") -> str:
    return f"{BILLING}/subscriptions/{scene['subscription_id']}/upgrade{tail}"


def _seats_url(scene: Mapping[str, uuid.UUID], tail: str = "") -> str:
    return f"{BILLING}/subscriptions/{scene['subscription_id']}/seats{tail}"


def _student(sm: sessionmaker[Session], **kwargs: Any) -> dict[str, uuid.UUID]:
    return student_with_plan(sm, price=10_000, allowance_units=1_000, **kwargs)


def _update_sub(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID], **values: Any) -> None:
    with sm.begin() as session:
        session.execute(
            sa.update(Subscription)
            .where(Subscription.id == scene["subscription_id"])
            .values(**values)
        )


def _deliver(sm: sessionmaker[Session], payment_id: str, *, at: datetime = NOW) -> None:
    """Pay ``payment_id`` through the real callback path (the handler runs in it)."""
    payment = _payment(sm, payment_id)
    assert payment.paymob_order_id is not None
    obj = transaction_obj(
        txn_id=next(_txn_ids),
        order_id=payment.paymob_order_id,
        merchant_order_id=str(payment.id),
        amount_cents=payment.amount_minor,
    )
    with sm.begin() as session:
        BillingService(
            session, _CheckoutClient(), PAYMOB_SETTINGS, now=lambda: at
        ).apply_transaction_callback(obj)


# ---------------------------------------------------------------------------
# Upgrade.
# ---------------------------------------------------------------------------


def test_the_payer_upgrades_and_gets_exactly_a_checkout(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    seed_saved_card(sm, scene["payer_id"], token="tok_payer_1")
    target = _tier(sm)

    res = h.as_user(scene["payer_id"], Role.student).post(
        _upgrade_url(scene), json={"planTierId": str(target)}
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert set(body) == {"paymentId", "checkoutUrl"}
    url = urlparse(body["checkoutUrl"])
    assert body["checkoutUrl"].startswith(h.paymob.checkout_base)
    query = parse_qs(url.query)
    assert set(query) >= {"publicKey", "clientSecret"}
    (intention,) = h.fake.intentions
    assert intention["payment_methods"] == [CARD_INTEGRATION_ID]
    assert set(intention["card_tokens"]) == {"tok_payer_1", "tok_card_1"}
    payment = _payment(sm, body["paymentId"])
    assert payment.purpose is PaymentPurpose.upgrade_proration
    assert payment.payer_user_id == scene["payer_id"]
    assert payment.amount_minor == 5_000


def test_a_parent_payer_upgrades_the_childs_plan(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    parent = seed_user(sm, Role.parent)
    scene = _student(sm, payer_id=parent)
    link_parent(sm, parent_id=parent, child_id=scene["student_id"])
    target = _tier(sm)

    res = h.as_user(parent, Role.parent).post(_upgrade_url(scene), json={"planTierId": str(target)})

    assert res.status_code == 201, res.text
    payment = _payment(sm, res.json()["paymentId"])
    assert payment.payer_user_id == parent
    assert payment.beneficiary_user_id == scene["student_id"]


def test_everyone_but_the_payer_gets_one_identical_404_and_no_intention(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    parent = seed_user(sm, Role.parent)
    scene = _student(sm, payer_id=parent)
    link_parent(sm, parent_id=parent, child_id=scene["student_id"])
    stranger = seed_user(sm, Role.parent)
    unlinked = seed_user(sm, Role.parent)
    other_student = seed_user(sm, Role.student)
    target = _tier(sm)
    body = {"planTierId": str(target)}

    bodies = []
    for who, role in (
        (scene["student_id"], Role.student),  # the beneficiary
        (stranger, Role.parent),
        (unlinked, Role.parent),
        (other_student, Role.student),
    ):
        for tail, payload in (("", body), ("/quote", body)):
            res = h.as_user(who, role).post(_upgrade_url(scene, tail), json=payload)
            assert res.status_code == 404, (who, tail, res.text)
            bodies.append(res.json())
    assert all(b == bodies[0] for b in bodies)
    assert bodies[0]["detail"]["error"] == "not_found"
    assert h.fake.intentions == []
    assert _payments(sm, PaymentPurpose.upgrade_proration) == []


def test_an_unlinked_payer_parent_is_refused_even_as_the_payer_of_record(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The payer of record loses access when the parent-child link is gone (DV-9)."""
    sm = pg_sessionmaker
    h = Harness(sm)
    parent = seed_user(sm, Role.parent)
    scene = _student(sm, payer_id=parent)  # never linked
    target = _tier(sm)

    res = h.as_user(parent, Role.parent).post(_upgrade_url(scene), json={"planTierId": str(target)})

    assert res.status_code == 404
    assert h.fake.intentions == []


def test_upgrade_quote_matches_the_checkout_and_writes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    target = _tier(sm)

    res = h.as_user(scene["payer_id"], Role.student).post(
        _upgrade_url(scene, "/quote"), json={"planTierId": str(target)}
    )

    assert res.status_code == 200, res.text
    quote = res.json()
    assert set(quote) == {"amountMinor", "currency", "allowanceUnits", "periodEnd"}
    assert quote["amountMinor"] == 5_000
    assert quote["currency"] == "EGP"
    assert quote["allowanceUnits"] == 1_000
    assert h.fake.intentions == []
    assert _payments(sm, PaymentPurpose.upgrade_proration) == []


def test_the_fallback_flag_off_is_a_409_that_names_cancel_and_resubscribe(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm, settings=paymob_settings(subscription_amount_updatable=False))
    scene = _student(sm)
    target = _tier(sm)

    res = h.as_user(scene["payer_id"], Role.student).post(
        _upgrade_url(scene), json={"planTierId": str(target)}
    )

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["error"] == "upgrade_unavailable"
    assert detail["next"] == "cancel_and_resubscribe"
    assert h.fake.intentions == []


def test_a_teacher_with_extra_seats_cannot_upgrade_to_a_plan_that_sells_none(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm, included=2, seat_price=2_000, price=30_000, extra=2)
    target = seed_tier(
        sm,
        audience=PlanAudience.teacher,
        price_minor=60_000,
        included_seats=10,
        extra_seat_price_minor=0,
    )

    res = h.as_user(scene["teacher_id"], Role.teacher).post(
        _upgrade_url(scene), json={"planTierId": str(target)}
    )

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["error"] == "seats_not_sold"
    assert detail["extraSeats"] == 2
    assert h.fake.intentions == []


# ---------------------------------------------------------------------------
# Extra seats and seat reduction.
# ---------------------------------------------------------------------------


def test_the_teacher_buys_seats_and_gets_a_checkout(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm)

    res = h.as_user(scene["teacher_id"], Role.teacher).post(_seats_url(scene), json={"seats": 2})

    assert res.status_code == 201, res.text
    assert set(res.json()) == {"paymentId", "checkoutUrl"}
    payment = _payment(sm, res.json()["paymentId"])
    assert payment.purpose is PaymentPurpose.extra_seats
    assert payment.seat_quantity == 2
    (intention,) = h.fake.intentions
    assert intention["payment_methods"] == [CARD_INTEGRATION_ID]


def test_the_seat_quote_has_the_four_quote_keys_and_no_allowance(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm)

    res = h.as_user(scene["teacher_id"], Role.teacher).post(
        _seats_url(scene, "/quote"), json={"seats": 2}
    )

    assert res.status_code == 200, res.text
    quote = res.json()
    assert set(quote) == {"amountMinor", "currency", "allowanceUnits", "periodEnd"}
    assert quote["allowanceUnits"] is None
    assert quote["amountMinor"] == 2_000  # 2 seats x 2 000 x half the period
    assert h.fake.intentions == []


def test_another_teacher_gets_404_on_checkout_quote_and_reduction(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm, extra=2)
    other = seed_user(sm, Role.teacher)
    client = h.as_user(other, Role.teacher)

    responses = [
        client.post(_seats_url(scene), json={"seats": 1}),
        client.post(_seats_url(scene, "/quote"), json={"seats": 1}),
        client.put(_seats_url(scene, "/pending"), json={"extraSeats": 0}),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert all(r.json() == responses[0].json() for r in responses)
    assert h.fake.intentions == []
    assert _payments(sm, PaymentPurpose.extra_seats) == []
    with sm() as session:
        sub = session.get(Subscription, scene["subscription_id"])
        assert sub is not None
        assert sub.pending_extra_seats is None


@pytest.mark.parametrize("role", [Role.student, Role.parent])
def test_a_student_or_parent_is_403_on_every_seat_route(
    pg_sessionmaker: sessionmaker[Session], role: Role
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm)
    client = h.as_user(seed_user(sm, role), role)

    assert client.post(_seats_url(scene), json={"seats": 1}).status_code == 403
    assert client.post(_seats_url(scene, "/quote"), json={"seats": 1}).status_code == 403
    assert client.put(_seats_url(scene, "/pending"), json={"extraSeats": 0}).status_code == 403
    assert h.fake.intentions == []


def test_the_acting_teacher_header_never_reaches_the_leads_seat_routes(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm, extra=2)
    assistant = seed_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=scene["teacher_id"], assistant_id=assistant)
    client = h.as_user(assistant, Role.teacher)
    headers = {ACTING: str(scene["teacher_id"])}

    responses = [
        client.post(_seats_url(scene), json={"seats": 1}, headers=headers),
        client.post(_seats_url(scene, "/quote"), json={"seats": 1}, headers=headers),
        client.put(_seats_url(scene, "/pending"), json={"extraSeats": 0}, headers=headers),
        client.post(_upgrade_url(scene), json={"planTierId": str(uuid.uuid4())}, headers=headers),
        client.get(f"{BILLING}/auto-topup", headers=headers),
    ]

    assert [r.status_code for r in responses[:4]] == [404, 404, 404, 404]
    assert h.fake.intentions == []
    with sm() as session:
        sub = session.get(Subscription, scene["subscription_id"])
        assert sub is not None
        assert sub.pending_extra_seats is None


def test_reduction_below_the_seated_students_is_409_seats_in_use(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm, included=1, extra=3)
    for _ in range(3):
        seed_seat(sm, teacher_id=scene["teacher_id"], student_id=seed_user(sm, Role.student))

    res = h.as_user(scene["teacher_id"], Role.teacher).put(
        _seats_url(scene, "/pending"), json={"extraSeats": 0}
    )

    assert res.status_code == 409
    assert _error(res) == "seats_in_use"


def test_a_reduction_is_scheduled_and_the_wire_shape_is_wire_seats(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm, included=1, extra=3)
    client = h.as_user(scene["teacher_id"], Role.teacher)

    res = client.put(_seats_url(scene, "/pending"), json={"extraSeats": 1})

    assert res.status_code == 200, res.text
    assert res.json() == {"extraSeats": 3, "pendingExtraSeats": 1}
    with sm() as session:
        sub = session.get(Subscription, scene["subscription_id"])
        assert sub is not None
        assert sub.pending_extra_seats == 1  # committed: a fresh session sees it
    # Asking for the current count clears it.
    cleared = client.put(_seats_url(scene, "/pending"), json={"extraSeats": 3})
    assert cleared.json() == {"extraSeats": 3, "pendingExtraSeats": None}


def test_seat_bodies_are_validated(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm)
    client = h.as_user(scene["teacher_id"], Role.teacher)

    assert client.post(_seats_url(scene), json={"seats": 0}).status_code == 422
    assert client.post(_seats_url(scene), json={"seats": 101}).status_code == 422
    assert client.post(_seats_url(scene, "/quote"), json={"seats": -1}).status_code == 422
    assert client.put(_seats_url(scene, "/pending"), json={"extraSeats": -1}).status_code == 422
    assert client.put(_seats_url(scene, "/pending"), json={"extraSeats": 201}).status_code == 422
    assert h.fake.intentions == []


def test_the_seat_ceiling_refusal_is_422_invalid_seats(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm)
    with sm.begin() as session:
        session.execute(sa.text("UPDATE billing_settings SET max_extra_seats = 1"))
    try:
        res = h.as_user(scene["teacher_id"], Role.teacher).post(
            _seats_url(scene), json={"seats": 2}
        )
    finally:
        with sm.begin() as session:
            session.execute(sa.text("UPDATE billing_settings SET max_extra_seats = 200"))

    assert res.status_code == 422
    assert _error(res) == "invalid_seats"


# ---------------------------------------------------------------------------
# The frontend contract (§7).
# ---------------------------------------------------------------------------


def test_extra_keys_are_a_422_on_every_charge_body(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    teacher = teacher_with_plan(sm, extra=1)
    student = _student(sm)
    target = _tier(sm)
    t_client = h.as_user(teacher["teacher_id"], Role.teacher)
    assert t_client.post(_seats_url(teacher), json={"seats": 1, "priceMinor": 1}).status_code == 422
    assert (
        t_client.post(_seats_url(teacher, "/quote"), json={"seats": 1, "x": 1}).status_code == 422
    )
    assert (
        t_client.put(_seats_url(teacher, "/pending"), json={"extraSeats": 0, "x": 1}).status_code
        == 422
    )
    s_client = h.as_user(student["payer_id"], Role.student)
    assert (
        s_client.post(
            _upgrade_url(student), json={"planTierId": str(target), "amountMinor": 1}
        ).status_code
        == 422
    )
    assert (
        s_client.post(
            _upgrade_url(student, "/quote"), json={"planTierId": "not-a-uuid"}
        ).status_code
        == 422
    )
    assert h.fake.intentions == []


def test_a_payer_with_no_saved_card_still_gets_a_checkout_and_no_saved_card_is_never_sent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    student = _student(sm, card=False)
    target = _tier(sm)
    teacher = teacher_with_plan(sm, card=False)

    up = h.as_user(student["payer_id"], Role.student).post(
        _upgrade_url(student), json={"planTierId": str(target)}
    )
    seats = h.as_user(teacher["teacher_id"], Role.teacher).post(
        _seats_url(teacher), json={"seats": 1}
    )

    assert (up.status_code, seats.status_code) == (201, 201)
    assert all("card_tokens" not in body for body in h.fake.intentions)


_CONFLICTS = [
    # (what to set up, the code the UI maps to copy)
    "charge_in_flight",
    "plan_change_pending",
    "seat_reduction_pending",
    "seat_charge_overdue",
    "period_ending",
]


def test_every_conflict_code_the_ui_reads_is_a_409_with_detail_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    target = _tier(sm)

    # plan_change_pending (upgrade): a cancel is scheduled.
    s1 = _student(sm)
    _update_sub(sm, s1, cancel_at_period_end=True)
    r1 = h.as_user(s1["payer_id"], Role.student).post(
        _upgrade_url(s1), json={"planTierId": str(target)}
    )
    # period_ending: the period has run out at the injected clock.
    s2 = _student(sm, start=T0 - timedelta(days=30), end=NOW)
    r2 = h.as_user(s2["payer_id"], Role.student).post(
        _upgrade_url(s2), json={"planTierId": str(target)}
    )
    # seat_reduction_pending and seat_charge_overdue on a teacher plan.
    t1 = teacher_with_plan(sm, included=1, extra=2, pending=1)
    r3 = h.as_user(t1["teacher_id"], Role.teacher).post(_seats_url(t1), json={"seats": 1})
    t2 = teacher_with_plan(sm)
    _update_sub(sm, t2, extra_seat_grace_until=NOW + timedelta(days=1))
    r4 = h.as_user(t2["teacher_id"], Role.teacher).post(_seats_url(t2), json={"seats": 1})
    # charge_in_flight: a pending upgrade payment.
    s3 = _student(sm)
    seed_payment_row(
        sm,
        payer_id=s3["payer_id"],
        beneficiary_id=s3["user_id"],
        purpose=PaymentPurpose.upgrade_proration,
        amount_minor=5_000,
        status=PaymentStatus.pending,
        subscription_id=s3["subscription_id"],
        plan_tier_id=target,
    )
    r5 = h.as_user(s3["payer_id"], Role.student).post(
        _upgrade_url(s3), json={"planTierId": str(target)}
    )

    codes = [_error(r) for r in (r1, r2, r3, r4, r5)]
    assert [r.status_code for r in (r1, r2, r3, r4, r5)] == [409] * 5
    assert codes == [
        "plan_change_pending",
        "period_ending",
        "seat_reduction_pending",
        "seat_charge_overdue",
        "charge_in_flight",
    ]
    assert h.fake.intentions == []


def test_seats_in_use_and_exceed_new_tier_carry_their_numbers_and_stay_409(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm, included=1, extra=2, price=10_000, seat_price=1_000)
    for _ in range(3):
        seed_seat(sm, teacher_id=scene["teacher_id"], student_id=seed_user(sm, Role.student))
    # A pricier plan, but with fewer included seats than the 3 active; the 2 extras are sold
    # there, so capacity is included + usable extras and in-use is under it: no refusal. Make the
    # in-use count exceed it by leaving no extras.
    target = seed_tier(
        sm,
        audience=PlanAudience.teacher,
        price_minor=40_000,
        included_seats=1,
        extra_seat_price_minor=1_500,
    )
    _update_sub(sm, scene, extra_seats=0, pending_extra_seats=None)
    res = h.as_user(scene["teacher_id"], Role.teacher).post(
        _upgrade_url(scene), json={"planTierId": str(target)}
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["error"] == "seats_exceed_new_tier"
    assert detail["inUse"] == 3
    assert detail["capacity"] == 1


def test_a_reduction_lock_and_the_other_seat_codes_are_409_with_copy() -> None:
    for code in (
        "seat_reduction_locked",
        "seats_changing",
        "seats_over_limit",
        "seats_not_sold",
        "not_an_upgrade",
        "upgrade_unavailable",
        "seat_reduction_unavailable",
        "not_a_teacher_plan",
        "not_a_reduction",
        "subscription_not_active",
        "cap_below_pack_price",
        "managed_by_another_payer",
        "no_saved_card",
        "some_future_code",
    ):
        exc = charge_error(MerchantChargeError(code, "text"))
        assert exc.status_code == 409, code
        assert exc.detail["error"] == code  # type: ignore[index]
        assert exc.detail["message"]  # type: ignore[index]
    for code, status in (
        ("not_found", 404),
        ("tier_not_found", 404),
        ("pack_not_found", 404),
        ("card_not_found", 404),
        ("invalid_seats", 422),
        ("invalid_settings", 422),
        ("payments_unavailable", 503),
        ("unknown_payer", 403),
    ):
        assert charge_error(MerchantChargeError(code, "text")).status_code == status, code
    # The 503 never echoes the internal reason, and an unknown payer never echoes the id.
    internal = charge_error(MerchantChargeError("payments_unavailable", "ceiling row missing"))
    assert internal.detail["message"] == billing_router._UNAVAILABLE  # type: ignore[index]
    gone = charge_error(MerchantChargeError("unknown_payer", "The payer has no account"))
    assert gone.detail["message"] == "Billing is not available"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Unknown outcome, outage, pending vs created, phone, rate limit.
# ---------------------------------------------------------------------------


def test_an_unknown_paymob_outcome_is_503_and_keeps_the_row_created_and_a_retry_is_allowed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    target = _tier(sm)
    client = h.as_user(scene["payer_id"], Role.student)
    h.fake.intention_response = PaymobError("timeout", timeout=True)

    res = client.post(_upgrade_url(scene), json={"planTierId": str(target)})

    assert res.status_code == 503
    detail = res.json()["detail"]
    assert detail["error"] == "payments_unavailable"
    assert detail["message"]
    (row,) = _payments(sm, PaymentPurpose.upgrade_proration)
    assert row.status is PaymentStatus.created  # R20b: reconcile decides
    h.fake.intention_response = dict(INTENTION_RESPONSE)
    retry = client.post(_upgrade_url(scene), json={"planTierId": str(target)})
    assert retry.status_code == 201  # a created row never blocks, so not a 409


def test_a_definite_paymob_refusal_is_503_and_the_row_is_failed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm)
    h.fake.intention_response = PaymobError("bad request", status_code=400)

    res = h.as_user(scene["teacher_id"], Role.teacher).post(_seats_url(scene), json={"seats": 1})

    assert res.status_code == 503
    assert _error(res) == "payments_unavailable"
    (row,) = _payments(sm, PaymentPurpose.extra_seats)
    assert row.status is PaymentStatus.failed


def test_an_unconfigured_paymob_is_503_and_writes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm, settings=paymob_settings(card_integration_id=None))
    scene = _student(sm)
    target = _tier(sm)

    res = h.as_user(scene["payer_id"], Role.student).post(
        _upgrade_url(scene), json={"planTierId": str(target)}
    )

    assert res.status_code == 503
    assert _payments(sm, PaymentPurpose.upgrade_proration) == []
    assert h.fake.intentions == []


def test_an_abandoned_created_upgrade_does_not_block_but_a_pending_one_does(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    target = _tier(sm)
    client = h.as_user(scene["payer_id"], Role.student)
    first = client.post(_upgrade_url(scene), json={"planTierId": str(target)})
    assert first.status_code == 201

    second = client.post(_upgrade_url(scene), json={"planTierId": str(target)})
    assert second.status_code == 201
    assert second.json()["paymentId"] != first.json()["paymentId"]

    with sm.begin() as session:
        session.execute(
            sa.update(Payment)
            .where(Payment.id == uuid.UUID(first.json()["paymentId"]))
            .values(status=PaymentStatus.pending)
        )
    third = client.post(_upgrade_url(scene), json={"planTierId": str(target)})
    assert third.status_code == 409
    assert _error(third) == "charge_in_flight"


def test_a_payer_without_a_phone_is_422_phone_required_and_nothing_is_written(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    teacher = teacher_with_plan(sm)
    target = _tier(sm)
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE users SET phone = NULL WHERE id IN (:a, :b)"),
            {"a": scene["payer_id"], "b": teacher["teacher_id"]},
        )

    up = h.as_user(scene["payer_id"], Role.student).post(
        _upgrade_url(scene), json={"planTierId": str(target)}
    )
    seats = h.as_user(teacher["teacher_id"], Role.teacher).post(
        _seats_url(teacher), json={"seats": 1}
    )

    for res in (up, seats):
        assert res.status_code == 422
        assert res.json()["detail"]["code"] == "phone_required"
    assert h.fake.intentions == []
    assert _payments(sm, PaymentPurpose.upgrade_proration) == []
    assert _payments(sm, PaymentPurpose.extra_seats) == []


def test_the_sixth_checkout_post_in_a_minute_is_429_and_quotes_are_unaffected(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm, checkout_limit=5)
    scene = _student(sm)
    teacher = teacher_with_plan(sm)
    target = _tier(sm)
    client = h.as_user(scene["payer_id"], Role.student)
    for _ in range(5):
        assert client.post(_upgrade_url(scene), json={"planTierId": str(target)}).status_code == 201

    sixth = client.post(_upgrade_url(scene), json={"planTierId": str(target)})

    assert sixth.status_code == 429
    assert int(sixth.headers["Retry-After"]) >= 1
    assert sixth.json()["detail"]["error"] == "rate_limited"
    assert len(h.fake.intentions) == 5
    quote = client.post(_upgrade_url(scene, "/quote"), json={"planTierId": str(target)})
    assert quote.status_code == 200
    # The budget is per payer and shared with the pack and subscription checkout; another user has
    # their own, and the seat checkout draws on the same bucket as the upgrade for one payer.
    other = h.as_user(teacher["teacher_id"], Role.teacher)
    assert other.post(_seats_url(teacher), json={"seats": 1}).status_code == 201
    assert h.limiter.allow(str(scene["payer_id"])) is False


def test_the_seat_checkout_is_limited_and_shares_the_upgrade_budget(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm, checkout_limit=3)
    teacher = teacher_with_plan(sm)
    client = h.as_user(teacher["teacher_id"], Role.teacher)
    for _ in range(3):
        assert client.post(_seats_url(teacher), json={"seats": 1}).status_code == 201

    fourth = client.post(_seats_url(teacher), json={"seats": 1})

    assert fourth.status_code == 429
    assert fourth.json()["detail"]["error"] == "rate_limited"
    assert "Retry-After" in fourth.headers
    assert len(h.fake.intentions) == 3
    # The quote and the reduction are not limited.
    assert client.post(_seats_url(teacher, "/quote"), json={"seats": 1}).status_code == 200


# ---------------------------------------------------------------------------
# GET /payments/{id}: creditedUnits and the explicit outcome.
# ---------------------------------------------------------------------------


def _upgrade_payment(h: Harness, scene: Mapping[str, uuid.UUID], target: uuid.UUID) -> str:
    res = h.as_user(scene["payer_id"], Role.student).post(
        _upgrade_url(scene), json={"planTierId": str(target)}
    )
    assert res.status_code == 201, res.text
    return str(res.json()["paymentId"])


def _status(h: Harness, user: uuid.UUID, role: Role, payment_id: str) -> dict[str, Any]:
    res = h.as_user(user, role).get(f"{BILLING}/payments/{payment_id}")
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def test_a_converted_upgrade_shows_credited_units_to_payer_and_beneficiary(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    parent = seed_user(sm, Role.parent)
    scene = _student(sm, payer_id=parent)
    link_parent(sm, parent_id=parent, child_id=scene["student_id"])
    target = _tier(sm)
    res = h.as_user(parent, Role.parent).post(_upgrade_url(scene), json={"planTierId": str(target)})
    payment_id = str(res.json()["paymentId"])
    # The plan ends before the payment clears: the handler turns it into credits.
    _update_sub(sm, scene, status=SubscriptionStatus.expired)

    _deliver(sm, payment_id, at=NOW + timedelta(days=20))

    for user, role in ((parent, Role.parent), (scene["student_id"], Role.student)):
        body = _status(h, user, role, payment_id)
        assert body["status"] == "paid"
        assert body["creditedUnits"] > 0
        assert body["outcome"] == "credited"


def test_a_normally_paid_upgrade_has_no_credited_units_and_reads_applied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    target = _tier(sm)
    payment_id = _upgrade_payment(h, scene, target)

    _deliver(sm, payment_id)

    body = _status(h, scene["payer_id"], Role.student, payment_id)
    assert body["status"] == "paid"
    assert body["creditedUnits"] is None
    assert body["outcome"] == "applied"


def test_a_paid_seat_purchase_reads_applied_with_no_credited_units(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm)
    res = h.as_user(scene["teacher_id"], Role.teacher).post(_seats_url(scene), json={"seats": 2})
    payment_id = str(res.json()["paymentId"])

    _deliver(sm, payment_id)

    body = _status(h, scene["teacher_id"], Role.teacher, payment_id)
    assert body["creditedUnits"] is None
    assert body["outcome"] == "applied"


def test_a_paid_but_unconvertible_upgrade_is_the_third_state_not_done(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """No credit rate: nothing applied, nothing credited. The page must not read "done"."""
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    target = _tier(sm)
    payment_id = _upgrade_payment(h, scene, target)
    _update_sub(sm, scene, status=SubscriptionStatus.expired)
    with sm.begin() as session:
        session.execute(sa.delete(CreditConversionRate))

    _deliver(sm, payment_id, at=NOW + timedelta(days=20))

    body = _status(h, scene["payer_id"], Role.student, payment_id)
    assert body["status"] == "paid"
    assert body["creditedUnits"] is None
    assert body["outcome"] == "needs_attention"


def test_a_paid_but_unconvertible_seat_purchase_is_the_third_state(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm)
    res = h.as_user(scene["teacher_id"], Role.teacher).post(_seats_url(scene), json={"seats": 2})
    payment_id = str(res.json()["paymentId"])
    _update_sub(sm, scene, status=SubscriptionStatus.expired)
    with sm.begin() as session:
        session.execute(sa.delete(CreditConversionRate))

    _deliver(sm, payment_id, at=NOW + timedelta(days=20))

    body = _status(h, scene["teacher_id"], Role.teacher, payment_id)
    assert body["creditedUnits"] is None
    assert body["outcome"] == "needs_attention"


def _no_rate(sm: sessionmaker[Session]) -> None:
    with sm.begin() as session:
        session.execute(sa.delete(CreditConversionRate))


def test_a_duplicate_upgrade_voided_without_a_rate_needs_attention_not_applied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Two checkouts to one tier, both paid: the second is void and unconvertible (I1, failure 1).

    The plan reads the target tier either way, so only the payment's own marker can tell the one
    that applied from the one that did not.
    """
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    target = _tier(sm)
    first = _upgrade_payment(h, scene, target)
    second = _upgrade_payment(h, scene, target)
    _no_rate(sm)

    _deliver(sm, second)
    _deliver(sm, first)

    applied = _status(h, scene["payer_id"], Role.student, second)
    voided = _status(h, scene["payer_id"], Role.student, first)
    assert applied["outcome"] == "applied"
    assert applied["voidReason"] is None
    assert voided["status"] == "paid"
    assert voided["creditedUnits"] is None
    assert voided["outcome"] == "needs_attention"
    assert voided["voidReason"] == "not_an_upgrade_now"
    row = _payment(sm, first)
    assert row.applied_at is None
    assert _payment(sm, second).applied_at is not None


def test_a_seat_purchase_voided_without_a_rate_needs_attention_when_the_teacher_holds_more(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Holds 5 extras, buys 2, the period rolls first, no rate: nothing was added (failure 2)."""
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm)
    _update_sub(sm, scene, extra_seats=5)
    res = h.as_user(scene["teacher_id"], Role.teacher).post(_seats_url(scene), json={"seats": 2})
    assert res.status_code == 201, res.text
    payment_id = str(res.json()["paymentId"])
    with sm() as session:
        sub = session.get(Subscription, scene["subscription_id"])
        assert sub is not None
        end = sub.current_period_end
    assert end is not None
    _update_sub(
        sm,
        scene,
        current_period_start=NOW + timedelta(days=1),
        current_period_end=end + timedelta(days=30),
    )
    _no_rate(sm)

    _deliver(sm, payment_id, at=NOW + timedelta(days=2))

    with sm() as session:
        sub = session.get(Subscription, scene["subscription_id"])
        assert sub is not None
        assert sub.extra_seats == 5  # nothing was added
    body = _status(h, scene["teacher_id"], Role.teacher, payment_id)
    assert body["outcome"] == "needs_attention"
    assert body["voidReason"] == "period_rolled"
    assert body["creditedUnits"] is None


def test_an_applied_upgrade_stays_applied_after_a_later_upgrade(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The first upgrade worked; a second one moves the plan on. It must not read as an alarm."""
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    mid = _tier(sm)
    top = _tier(sm, price_minor=40_000, allowance_units=6_000)
    first = _upgrade_payment(h, scene, mid)
    _deliver(sm, first)
    assert _status(h, scene["payer_id"], Role.student, first)["outcome"] == "applied"
    second = _upgrade_payment(h, scene, top)
    _deliver(sm, second)

    body = _status(h, scene["payer_id"], Role.student, first)

    assert body["outcome"] == "applied"
    assert body["voidReason"] is None


def test_a_converted_payment_reports_its_void_reason(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    payment_id = _upgrade_payment(h, scene, _tier(sm))
    _update_sub(sm, scene, status=SubscriptionStatus.expired)

    _deliver(sm, payment_id, at=NOW + timedelta(days=20))

    body = _status(h, scene["payer_id"], Role.student, payment_id)
    assert body["outcome"] == "credited"
    assert body["voidReason"] == "plan_ended"
    assert _payment(sm, payment_id).applied_at is None


def test_a_queued_renewal_seat_payment_has_no_outcome(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A paid ``extra_seat_renewal:`` row pays for seats that already exist: ``outcome`` is null.

    It has neither a marker nor credits, so without the ``dedupe_key`` gate it would read as
    "needs attention" for a charge that did exactly what it was for.
    """
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = teacher_with_plan(sm, extra=2)
    queued = seed_payment_row(
        sm,
        payer_id=scene["teacher_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=4_000,
        status=PaymentStatus.paid,
        subscription_id=scene["subscription_id"],
        seat_quantity=2,
        dedupe_key=f"extra_seat_renewal:{scene['period_id']}:1",
        paid_at=NOW,
    )

    body = _status(h, scene["teacher_id"], Role.teacher, str(queued))

    assert body["status"] == "paid"
    assert body["outcome"] is None


def test_unsettled_and_other_purpose_payments_have_no_outcome_or_credited_units(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    target = _tier(sm)
    created = _upgrade_payment(h, scene, target)
    pack = seed_pack(sm)
    pack_payment = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        purpose=PaymentPurpose.credit_pack,
        amount_minor=10_000,
        status=PaymentStatus.paid,
        credit_pack_id=pack,
        paid_at=NOW,
    )

    for payment_id in (created, str(pack_payment)):
        body = _status(h, scene["payer_id"], Role.student, payment_id)
        assert body["creditedUnits"] is None
        assert body["outcome"] is None


def test_a_stranger_cannot_read_a_charge_payment(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    scene = _student(sm)
    target = _tier(sm)
    payment_id = _upgrade_payment(h, scene, target)

    res = h.as_user(seed_user(sm, Role.student), Role.student).get(
        f"{BILLING}/payments/{payment_id}"
    )

    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Auto top-up.
# ---------------------------------------------------------------------------


def _put_body(pack: uuid.UUID, card: uuid.UUID | None, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "beneficiaryId": None,
        "enabled": True,
        "thresholdUnits": 500,
        "creditPackId": str(pack),
        "savedCardId": None if card is None else str(card),
        "monthlyCapMinor": 50_000,
    }
    body.update(overrides)
    return body


_AUTO_KEYS = {
    "beneficiaryId",
    "enabled",
    "thresholdUnits",
    "creditPackId",
    "savedCardId",
    "monthlyCapMinor",
    "spentThisMonthMinor",
    "currency",
    "disabledReason",
}


def test_a_balance_never_set_up_reads_as_disabled_with_nulls(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    student = seed_user(sm, Role.student)

    res = h.as_user(student, Role.student).get(f"{BILLING}/auto-topup")

    assert res.status_code == 200, res.text
    assert res.json() == {
        "beneficiaryId": str(student),
        "enabled": False,
        "thresholdUnits": None,
        "creditPackId": None,
        "savedCardId": None,
        "monthlyCapMinor": None,
        "spentThisMonthMinor": 0,
        "currency": "EGP",
        "disabledReason": None,
    }


def test_the_student_sets_and_reads_their_own_auto_top_up(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    student = seed_user(sm, Role.student)
    card = seed_saved_card(sm, student)
    pack = seed_pack(sm, price_minor=10_000)
    client = h.as_user(student, Role.student)

    put = client.put(f"{BILLING}/auto-topup", json=_put_body(pack, card))
    read = client.get(f"{BILLING}/auto-topup")

    assert put.status_code == 200, put.text
    assert set(put.json()) == _AUTO_KEYS
    assert put.json() == read.json()
    assert read.json()["enabled"] is True
    assert read.json()["savedCardId"] == str(card)
    with sm() as session:
        row = session.scalar(
            sa.select(AutoTopupSettings).where(AutoTopupSettings.beneficiary_user_id == student)
        )
        assert row is not None
        assert row.consented_at is not None


def test_a_parent_sets_auto_top_up_for_a_linked_child(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm, Role.student)
    link_parent(sm, parent_id=parent, child_id=child)
    card = seed_saved_card(sm, parent)
    pack = seed_pack(sm, price_minor=10_000)
    client = h.as_user(parent, Role.parent)

    put = client.put(f"{BILLING}/auto-topup", json=_put_body(pack, card, beneficiaryId=str(child)))
    read = client.get(f"{BILLING}/auto-topup", params={"beneficiaryId": str(child)})

    assert put.status_code == 200, put.text
    assert read.json()["beneficiaryId"] == str(child)
    assert read.json()["enabled"] is True
    # The child, who sees the balance but not the billing, gets 404 (managed by the parent)
    # on read and 409 on write.
    child_client = h.as_user(child, Role.student)
    assert child_client.get(f"{BILLING}/auto-topup").status_code == 404
    other_card = seed_saved_card(sm, child)
    mine = child_client.put(f"{BILLING}/auto-topup", json=_put_body(pack, other_card))
    assert mine.status_code == 409
    assert _error(mine) == "managed_by_another_payer"


def test_a_stranger_or_unlinked_parent_is_403_not_linked_parent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm, Role.student)  # never linked to ``parent``
    teacher_child = seed_user(sm, Role.teacher)
    link_parent(sm, parent_id=parent, child_id=teacher_child)  # linked, but not a student
    card = seed_saved_card(sm, parent)
    pack = seed_pack(sm, price_minor=10_000)
    client = h.as_user(parent, Role.parent)

    for target in (child, teacher_child):
        read = client.get(f"{BILLING}/auto-topup", params={"beneficiaryId": str(target)})
        put = client.put(
            f"{BILLING}/auto-topup", json=_put_body(pack, card, beneficiaryId=str(target))
        )
        assert read.status_code == 403, read.text
        assert put.status_code == 403, put.text
        assert _error(read) == "not_linked_parent"
        assert _error(put) == "not_linked_parent"
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(AutoTopupSettings)) == 0


def test_a_parent_must_name_a_child_and_others_cannot_name_another_beneficiary(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    parent = seed_user(sm, Role.parent)
    student = seed_user(sm, Role.student)
    other = seed_user(sm, Role.student)
    card = seed_saved_card(sm, student)
    pack = seed_pack(sm, price_minor=10_000)

    assert h.as_user(parent, Role.parent).get(f"{BILLING}/auto-topup").status_code == 422
    client = h.as_user(student, Role.student)
    assert (
        client.get(f"{BILLING}/auto-topup", params={"beneficiaryId": str(other)}).status_code == 403
    )
    assert (
        client.put(
            f"{BILLING}/auto-topup", json=_put_body(pack, card, beneficiaryId=str(other))
        ).status_code
        == 403
    )


def test_a_foreign_card_is_404_and_a_cap_below_the_price_is_409(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    student = seed_user(sm, Role.student)
    stranger = seed_user(sm, Role.student)
    foreign = seed_saved_card(sm, stranger)
    own = seed_saved_card(sm, student)
    pack = seed_pack(sm, price_minor=10_000)
    client = h.as_user(student, Role.student)

    foreign_card = client.put(f"{BILLING}/auto-topup", json=_put_body(pack, foreign))
    low_cap = client.put(f"{BILLING}/auto-topup", json=_put_body(pack, own, monthlyCapMinor=9_999))
    unknown_pack = client.put(f"{BILLING}/auto-topup", json=_put_body(uuid.uuid4(), own))
    no_card = client.put(f"{BILLING}/auto-topup", json=_put_body(pack, None))

    assert foreign_card.status_code == 404
    assert _error(foreign_card) == "card_not_found"
    assert low_cap.status_code == 409
    assert _error(low_cap) == "cap_below_pack_price"
    assert unknown_pack.status_code == 404
    assert _error(unknown_pack) == "pack_not_found"
    assert no_card.status_code == 409
    assert _error(no_card) == "no_saved_card"


def test_a_switched_off_save_with_a_zero_cap_and_no_card_is_200(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    student = seed_user(sm, Role.student)
    pack = seed_pack(sm, price_minor=10_000)

    res = h.as_user(student, Role.student).put(
        f"{BILLING}/auto-topup",
        json=_put_body(pack, None, enabled=False, monthlyCapMinor=0),
    )

    assert res.status_code == 200, res.text
    assert res.json()["enabled"] is False
    assert res.json()["monthlyCapMinor"] == 0


def test_auto_top_up_bodies_are_validated(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    student = seed_user(sm, Role.student)
    card = seed_saved_card(sm, student)
    pack = seed_pack(sm, price_minor=10_000)
    client = h.as_user(student, Role.student)
    url = f"{BILLING}/auto-topup"

    assert client.put(url, json=_put_body(pack, card, thresholdUnits=0)).status_code == 422
    assert client.put(url, json=_put_body(pack, card, monthlyCapMinor=-1)).status_code == 422
    assert client.put(url, json=_put_body(pack, card, thresholdUnits=10**12 + 1)).status_code == 422
    assert client.put(url, json={**_put_body(pack, card), "extra": 1}).status_code == 422
    assert client.put(url, json=_put_body(pack, card, creditPackId="nope")).status_code == 422


def test_auto_top_up_without_a_phone_is_422_phone_required(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    student = seed_user(sm, Role.student, phone=None)
    card = seed_saved_card(sm, student)
    pack = seed_pack(sm, price_minor=10_000)

    res = h.as_user(student, Role.student).put(f"{BILLING}/auto-topup", json=_put_body(pack, card))

    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "phone_required"


class _UniqueViolation(Exception):
    """What psycopg raises for a duplicate key: SQLSTATE 23505."""

    sqlstate = "23505"


def test_a_first_save_race_is_retried_as_an_upsert(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two first saves at once: the loser's insert hits the unique constraint and is retried."""
    sm = pg_sessionmaker
    h = Harness(sm)
    student = seed_user(sm, Role.student)
    card = seed_saved_card(sm, student)
    pack = seed_pack(sm, price_minor=10_000)
    real = billing_router.put_auto_topup
    calls: list[int] = []

    def racing(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("INSERT", {}, _UniqueViolation("uq_auto_topup_beneficiary"))
        return real(*args, **kwargs)

    monkeypatch.setattr(billing_router, "put_auto_topup", racing)

    res = h.as_user(student, Role.student).put(f"{BILLING}/auto-topup", json=_put_body(pack, card))

    assert res.status_code == 200, res.text
    assert len(calls) == 2
    assert res.json()["enabled"] is True


def test_a_save_that_keeps_colliding_is_409_never_500(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    student = seed_user(sm, Role.student)
    card = seed_saved_card(sm, student)
    pack = seed_pack(sm, price_minor=10_000)

    def always(*args: Any, **kwargs: Any) -> Any:
        raise IntegrityError("INSERT", {}, _UniqueViolation("uq_auto_topup_beneficiary"))

    monkeypatch.setattr(billing_router, "put_auto_topup", always)

    res = h.as_user(student, Role.student).put(f"{BILLING}/auto-topup", json=_put_body(pack, card))

    assert res.status_code == 409
    assert _error(res) == "settings_changing"


def test_the_auto_top_up_routes_never_read_the_acting_teacher_header(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    teacher = seed_user(sm, Role.teacher)
    assistant = seed_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=teacher, assistant_id=assistant)

    res = h.as_user(assistant, Role.teacher).get(
        f"{BILLING}/auto-topup", headers={ACTING: str(teacher)}
    )

    assert res.status_code == 200
    assert res.json()["beneficiaryId"] == str(assistant)


def test_the_charge_routes_refuse_admins(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    client = h.as_user(uuid.uuid4(), Role.platform_admin)
    sid = uuid.uuid4()

    assert client.get(f"{BILLING}/auto-topup").status_code == 403
    assert client.put(f"{BILLING}/auto-topup", json={}).status_code == 403
    for tail in ("/upgrade", "/upgrade/quote", "/seats", "/seats/quote"):
        assert client.post(f"{BILLING}/subscriptions/{sid}{tail}", json={}).status_code == 403
    assert client.put(f"{BILLING}/subscriptions/{sid}/seats/pending", json={}).status_code == 403
    assert h.fake.intentions == []


def test_a_different_integrity_error_is_not_swallowed_as_a_race(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = pg_sessionmaker
    h = Harness(sm)
    h.http = TestClient(h.app, raise_server_exceptions=False)
    student = seed_user(sm, Role.student)
    card = seed_saved_card(sm, student)
    pack = seed_pack(sm, price_minor=10_000)

    def foreign_key(*args: Any, **kwargs: Any) -> Any:
        raise IntegrityError("INSERT", {}, Exception("violates foreign key"))

    monkeypatch.setattr(billing_router, "put_auto_topup", foreign_key)

    res = h.as_user(student, Role.student).put(f"{BILLING}/auto-topup", json=_put_body(pack, card))

    assert res.status_code == 500
