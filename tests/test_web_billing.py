"""/api/billing: catalogue, pack checkout, payment status, receipts, IDOR (spec §5.5, §7)."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.models.billing import (
    Payment,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    SavedCard,
)
from lemely.db.models.enums import PlanInterval, Role
from lemely.io.paymob.client import PaymobError
from lemely.runtime.config import PaymobSettings, Settings
from lemely.runtime.token_cipher import TokenCipher
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_settings
from lemely.web.deps_billing import (
    PublicCatalogueCache,
    get_billing_sessionmaker,
    get_checkout_limiter,
    get_paymob_client,
    get_public_catalogue_cache,
    get_public_catalogue_limiter,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from tests.paymob_fixtures import (
    FIXED_NOW,
    PAYMOB_SETTINGS,
    TEST_CARD_TOKEN_KEY,
    FakePaymobClient,
    link_parent,
    seed_pack,
    seed_payment,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def paymob() -> FakePaymobClient:
    return FakePaymobClient()


class _Clock:
    """A settable monotonic clock for the public-catalogue cache."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def cache_clock() -> _Clock:
    return _Clock()


@pytest.fixture
def client(
    migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient, cache_clock: _Clock
) -> Iterator[TestClient]:
    settings = Settings().model_copy(update={"paymob": PAYMOB_SETTINGS})
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_billing_sessionmaker] = lambda: migrated_sessionmaker
    app.dependency_overrides[get_paymob_client] = lambda: paymob
    app.dependency_overrides[get_checkout_limiter] = lambda: SlidingWindowLimiter(
        limit=100, window_seconds=60, clock=time.monotonic
    )
    app.dependency_overrides[get_public_catalogue_limiter] = lambda: SlidingWindowLimiter(
        limit=100, window_seconds=60, clock=time.monotonic
    )
    cache = PublicCatalogueCache(ttl_seconds=30.0, clock=cache_clock)
    app.dependency_overrides[get_public_catalogue_cache] = lambda: cache
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id=str(user_id), role=role.value
    )


def _tier(
    sm: sessionmaker[Session], code: str, audience: PlanAudience, *, active: bool = True
) -> None:
    with sm.begin() as session:
        session.add(
            PlanTier(
                code=code,
                name=code,
                price_minor=9900,
                audience=audience,
                is_active=active,
                allowance_units=5000,
            )
        )


def _keys(value: Any) -> set[str]:
    """Every dict key anywhere in a decoded JSON document."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


# -- catalogue ----------------------------------------------------------------


def test_catalogue_shows_the_callers_audience_and_active_packs_only(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    _tier(sm, "student_monthly", PlanAudience.student)
    _tier(sm, "teacher_monthly", PlanAudience.teacher)
    _tier(sm, "student_retired", PlanAudience.student, active=False)
    seed_pack(sm, code="pack_100", name="100 credits")
    seed_pack(sm, code="pack_old", is_active=False)

    _as(client, seed_user(sm), Role.student)
    body = client.get("/api/billing/catalogue").json()
    assert [t["code"] for t in body["planTiers"]] == ["student_monthly"]
    assert [p["code"] for p in body["creditPacks"]] == ["pack_100"]
    assert body["creditPacks"][0]["credits"] == 100
    assert "allowanceUnits" not in body["planTiers"][0]  # allowances stay hidden (§2.1)

    _as(client, seed_user(sm, Role.parent), Role.parent)
    assert [t["code"] for t in client.get("/api/billing/catalogue").json()["planTiers"]] == [
        "student_monthly"
    ]

    _as(client, seed_user(sm, Role.teacher), Role.teacher)
    assert [t["code"] for t in client.get("/api/billing/catalogue").json()["planTiers"]] == [
        "teacher_monthly"
    ]


def test_catalogue_hides_allowances_and_the_paymob_plan_link(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    _public_seed(migrated_sessionmaker)
    _as(client, seed_user(migrated_sessionmaker, Role.teacher), Role.teacher)
    response = client.get("/api/billing/catalogue")
    assert response.status_code == 200
    keys = {key.lower() for key in _keys(response.json())}
    assert not [k for k in keys if "paymob" in k or "allowance" in k], keys


# -- public pricing catalogue ----------------------------------------------------


def _public_seed(sm: sessionmaker[Session]) -> None:
    with sm.begin() as session:
        session.add_all(
            [
                PlanTier(
                    code="student_monthly",
                    name="Student",
                    price_minor=9900,
                    audience=PlanAudience.student,
                    allowance_units=5000,
                    interval=PlanInterval.monthly,
                    paymob_plan_id=1186,
                    paymob_plan_mode="test",
                    features={"papers": "unlimited"},
                ),
                PlanTier(
                    code="teacher_monthly",
                    name="Teacher",
                    price_minor=49900,
                    audience=PlanAudience.teacher,
                    allowance_units=20000,
                    interval=PlanInterval.monthly,
                    paymob_plan_id=1187,
                    paymob_plan_mode="test",
                    included_seats=30,
                    seat_allowance_units=700,
                    extra_seat_price_minor=1500,
                ),
                PlanTier(
                    code="student_retired",
                    name="Old",
                    price_minor=5000,
                    audience=PlanAudience.student,
                    interval=PlanInterval.monthly,
                    is_active=False,
                ),
            ]
        )
    seed_pack(sm, code="pack_100", name="100 credits", units=100, price_minor=10000)
    seed_pack(sm, code="pack_old", is_active=False)
    seed_pack(sm, code="signup_student", units=200, price_minor=0, is_active=False)


def test_public_catalogue_needs_no_auth_and_hides_internals(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    _public_seed(migrated_sessionmaker)
    response = client.get("/api/billing/public-catalogue", params={"audience": "student"})
    assert response.status_code == 200
    assert response.json() == {
        "audience": "student",
        "planTiers": [
            {
                "code": "student_monthly",
                "name": "Student",
                "audience": "student",
                "interval": "monthly",
                "priceMinor": 9900,
                "currency": "EGP",
                "features": {"papers": "unlimited"},
                "includedSeats": None,
                "extraSeatPriceMinor": None,
            }
        ],
        "creditPacks": [
            {
                "code": "pack_100",
                "name": "100 credits",
                "units": 100,
                "priceMinor": 10000,
                "currency": "EGP",
            }
        ],
    }
    hidden_markers = ("paymob", "allowance", "Allowance", 'Id"', "student_retired")
    for hidden in (*hidden_markers, "pack_old", "signup_"):
        assert hidden not in response.text, hidden


def test_public_catalogue_sends_the_interval_the_frontend_adapter_reads(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """web/src/lib/billingAdapters.ts `toInterval` accepts "monthly" and "yearly" only."""
    with migrated_sessionmaker.begin() as session:
        session.add(
            PlanTier(
                code="student_yearly",
                name="Student yearly",
                price_minor=99000,
                audience=PlanAudience.student,
                interval=PlanInterval.yearly,
            )
        )
    body = client.get("/api/billing/public-catalogue", params={"audience": "student"}).json()
    assert [t["interval"] for t in body["planTiers"]] == ["yearly"]


def test_public_catalogue_filters_by_audience(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    _public_seed(migrated_sessionmaker)
    body = client.get("/api/billing/public-catalogue", params={"audience": "teacher"}).json()
    assert body["audience"] == "teacher"
    (tier,) = body["planTiers"]
    assert tier["code"] == "teacher_monthly"
    assert tier["includedSeats"] == 30
    assert tier["extraSeatPriceMinor"] == 1500
    assert "seat_allowance" not in str(body) and "700" not in str(tier)
    assert [p["code"] for p in body["creditPacks"]] == ["pack_100"]


def test_public_catalogue_lists_only_sellable_tiers(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """A tier with no billing interval cannot be bought, so the pricing page never lists it."""
    sm = migrated_sessionmaker
    _public_seed(sm)
    _tier(sm, "student_no_interval", PlanAudience.student)  # active, but no interval
    body = client.get("/api/billing/public-catalogue", params={"audience": "student"}).json()
    assert [t["code"] for t in body["planTiers"]] == ["student_monthly"]
    _as(client, seed_user(sm), Role.student)  # the signed-in catalogue is unchanged
    signed_in = client.get("/api/billing/catalogue").json()
    assert "student_no_interval" in [t["code"] for t in signed_in["planTiers"]]


def test_public_catalogue_is_cached_per_audience_until_the_ttl_expires(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], cache_clock: _Clock
) -> None:
    """Bypassing the per-IP limiter cannot turn every request into a DB query."""
    sm = migrated_sessionmaker
    _public_seed(sm)
    url = "/api/billing/public-catalogue"
    first = client.get(url, params={"audience": "student"}).json()
    seed_pack(sm, code="pack_new", price_minor=20000)  # the catalogue changes underneath

    cache_clock.now += 29.0
    assert client.get(url, params={"audience": "student"}).json() == first  # a cache hit
    other = client.get(url, params={"audience": "teacher"}).json()  # keyed by audience
    assert other["audience"] == "teacher"
    assert "pack_new" in [p["code"] for p in other["creditPacks"]]

    cache_clock.now += 2.0  # 31 s after the first fill: expired
    refreshed = client.get(url, params={"audience": "student"}).json()
    assert [p["code"] for p in refreshed["creditPacks"]] == ["pack_100", "pack_new"]


def test_a_rate_limited_request_never_reaches_the_cache(client: TestClient) -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60, clock=lambda: 0.0)
    client.app.dependency_overrides[get_public_catalogue_limiter] = lambda: limiter  # type: ignore[attr-defined]
    url = "/api/billing/public-catalogue?audience=student"
    assert [client.get(url).status_code for _ in range(2)] == [200, 429]


@pytest.mark.parametrize("params", [{}, {"audience": "parent"}, {"audience": "admin"}])
def test_public_catalogue_requires_a_valid_audience(
    client: TestClient, params: dict[str, str]
) -> None:
    assert client.get("/api/billing/public-catalogue", params=params).status_code == 422


def test_public_catalogue_is_rate_limited_per_client(client: TestClient) -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: 0.0)
    client.app.dependency_overrides[get_public_catalogue_limiter] = lambda: limiter  # type: ignore[attr-defined]
    url = "/api/billing/public-catalogue?audience=student"
    codes = [client.get(url).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert int(client.get(url).headers["Retry-After"]) >= 1


def test_public_catalogue_limit_is_per_client_not_global(client: TestClient) -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60, clock=lambda: 0.0)
    client.app.dependency_overrides[get_public_catalogue_limiter] = lambda: limiter  # type: ignore[attr-defined]
    url = "/api/billing/public-catalogue?audience=student"
    first = client.get(url, headers={"X-Forwarded-For": "203.0.113.1"})
    again = client.get(url, headers={"X-Forwarded-For": "203.0.113.1"})
    other = client.get(url, headers={"X-Forwarded-For": "203.0.113.2"})
    assert (first.status_code, again.status_code, other.status_code) == (200, 429, 200)


# -- pack checkout --------------------------------------------------------------


def test_a_student_buys_a_pack_for_themselves(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    pack = seed_pack(sm, price_minor=10000)
    _as(client, student, Role.student)
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["checkoutUrl"].startswith(
        "https://eg.checkout.paymob.com/?publicKey=egy_pk_test_public"
    )
    assert "egy_sk_test_secret" not in response.text
    with sm() as session:
        payment = session.get(Payment, uuid.UUID(body["paymentId"]))
        assert payment is not None
        assert payment.payer_user_id == payment.beneficiary_user_id == student
        assert payment.amount_minor == 10000
    assert paymob.intentions[0]["amount"] == 10000


def test_the_client_cannot_set_the_price(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    _as(client, seed_user(sm), Role.student)
    pack = seed_pack(sm)
    response = client.post(
        "/api/billing/checkout/pack", json={"creditPackId": str(pack), "priceMinor": 1}
    )
    assert response.status_code == 422


def test_a_student_cannot_buy_for_someone_else(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    _as(client, seed_user(sm), Role.student)
    other = seed_user(sm)
    pack = seed_pack(sm)
    response = client.post(
        "/api/billing/checkout/pack",
        json={"creditPackId": str(pack), "beneficiaryId": str(other)},
    )
    assert response.status_code == 403
    assert paymob.intentions == []
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


def test_a_parent_buys_for_a_linked_child(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    link_parent(sm, parent_id=parent, child_id=child)
    pack = seed_pack(sm)
    _as(client, parent, Role.parent)
    response = client.post(
        "/api/billing/checkout/pack",
        json={"creditPackId": str(pack), "beneficiaryId": str(child)},
    )
    assert response.status_code == 201, response.text
    with sm() as session:
        payment = session.get(Payment, uuid.UUID(response.json()["paymentId"]))
        assert payment is not None
        assert (payment.payer_user_id, payment.beneficiary_user_id) == (parent, child)


def test_a_parent_cannot_buy_for_an_unlinked_student(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    """The service's ``NotLinkedToBeneficiary`` is a 403, never a 404 or a 500."""
    sm = migrated_sessionmaker
    _as(client, seed_user(sm, Role.parent), Role.parent)
    stranger = seed_user(sm)
    pack = seed_pack(sm)
    for beneficiary in (stranger, uuid.uuid4()):
        response = client.post(
            "/api/billing/checkout/pack",
            json={"creditPackId": str(pack), "beneficiaryId": str(beneficiary)},
        )
        assert response.status_code == 403  # same answer whether or not the user exists
    assert paymob.intentions == []
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


def test_a_parent_cannot_buy_for_a_child_linked_to_another_parent(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    mine, theirs = seed_user(sm, Role.parent), seed_user(sm, Role.parent)
    my_child, their_child = seed_user(sm), seed_user(sm)
    link_parent(sm, parent_id=mine, child_id=my_child)
    link_parent(sm, parent_id=theirs, child_id=their_child)
    _as(client, mine, Role.parent)
    response = client.post(
        "/api/billing/checkout/pack",
        json={"creditPackId": str(seed_pack(sm)), "beneficiaryId": str(their_child)},
    )
    assert response.status_code == 403


def test_a_parent_cannot_buy_a_pack_for_themselves(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    """Spec: a parent buys only for a linked child, never for their own account."""
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    link_parent(sm, parent_id=parent, child_id=seed_user(sm))
    _as(client, parent, Role.parent)
    response = client.post(
        "/api/billing/checkout/pack",
        json={"creditPackId": str(seed_pack(sm)), "beneficiaryId": str(parent)},
    )
    assert response.status_code == 403
    assert paymob.intentions == []
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


def test_a_parent_cannot_buy_for_a_linked_teacher(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    teacher = seed_user(sm, Role.teacher)
    link_parent(sm, parent_id=parent, child_id=teacher)
    _as(client, parent, Role.parent)
    response = client.post(
        "/api/billing/checkout/pack",
        json={"creditPackId": str(seed_pack(sm)), "beneficiaryId": str(teacher)},
    )
    assert response.status_code == 403
    assert paymob.intentions == []


def test_a_valid_token_without_a_users_row_is_403_not_500(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    ghost = uuid.uuid4()
    _as(client, ghost, Role.student)
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(seed_pack(sm))})
    assert response.status_code == 403
    assert str(ghost) not in response.text  # generic text, no id echoed
    assert paymob.intentions == []


def test_a_parent_must_name_the_child(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    _as(client, seed_user(sm, Role.parent), Role.parent)
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(seed_pack(sm))})
    assert response.status_code == 422


def test_unknown_and_inactive_packs_are_404(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    _as(client, seed_user(sm), Role.student)
    for pack in (uuid.uuid4(), seed_pack(sm, is_active=False)):
        response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)})
        assert response.status_code == 404


@pytest.mark.parametrize(
    "error",
    [
        PaymobError("boom", status_code=502),
        PaymobError("overloaded", status_code=503),
        PaymobError("timed out", timeout=True),
        PaymobError("connection reset"),
    ],
    ids=["502", "503", "timeout", "no-answer"],
)
def test_an_unknown_paymob_outcome_is_503_and_never_marks_the_payment_failed(
    client: TestClient,
    migrated_sessionmaker: sessionmaker[Session],
    paymob: FakePaymobClient,
    error: PaymobError,
) -> None:
    """Index R20b: Paymob may have created the order, so the payment stays open."""
    sm = migrated_sessionmaker
    _as(client, seed_user(sm), Role.student)
    paymob.intention_response = error
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(seed_pack(sm))})
    assert response.status_code == 503
    assert "try again" in response.json()["detail"]
    with sm() as session:
        payment = session.scalars(sa.select(Payment)).one()
        assert payment.status is PaymentStatus.created
        assert payment.next_reconcile_at is not None  # the reconcile job settles it by inquiry
    assert len(paymob.intentions) == 1  # never retried


def test_a_definite_paymob_refusal_is_503_and_marks_the_payment_failed(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    """A received 4xx means no order exists, so nothing can be paid (R20b)."""
    sm = migrated_sessionmaker
    _as(client, seed_user(sm), Role.student)
    paymob.intention_response = PaymobError("bad request", status_code=400)
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(seed_pack(sm))})
    assert response.status_code == 503
    assert "try again" in response.json()["detail"]
    assert "bad request" not in response.text  # the upstream message never reaches the client
    with sm() as session:
        payment = session.scalars(sa.select(Payment)).one()
        assert payment.status is PaymentStatus.failed
        assert payment.next_reconcile_at is None


def test_unconfigured_paymob_is_503(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    bare = Settings().model_copy(update={"paymob": PaymobSettings()})
    client.app.dependency_overrides[get_settings] = lambda: bare  # type: ignore[attr-defined]
    _as(client, seed_user(sm), Role.student)
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(seed_pack(sm))})
    assert response.status_code == 503
    assert paymob.intentions == []


def test_checkout_is_rate_limited_per_user(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    order_ids = iter(range(900_000_001, 900_000_100))

    def fresh_order(_body: dict[str, Any]) -> None:
        # Paymob numbers every order; ``uq_payments_paymob_order_id`` forbids a repeat.
        paymob.intention_response = {
            **paymob.intention_response,  # type: ignore[dict-item]
            "intention_order_id": next(order_ids),
        }

    paymob.on_intention = fresh_order
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: 0.0)
    client.app.dependency_overrides[get_checkout_limiter] = lambda: limiter  # type: ignore[attr-defined]
    _as(client, seed_user(sm), Role.student)
    pack = seed_pack(sm)
    codes = [
        client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)}).status_code
        for _ in range(3)
    ]
    assert codes == [201, 201, 429]
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)})
    assert int(response.headers["Retry-After"]) >= 1

    _as(client, seed_user(sm), Role.student)  # another user has a bucket of their own
    assert (
        client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)}).status_code
        == 201
    )


# -- payment status -------------------------------------------------------------


def test_payment_status_is_visible_to_payer_and_beneficiary_only(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    pack = seed_pack(sm, name="100 credits")
    pid = seed_payment(
        sm,
        payer=parent,
        beneficiary=child,
        pack_id=pack,
        status=PaymentStatus.paid,
        paid_at=FIXED_NOW,
    )
    for user, role in ((parent, Role.parent), (child, Role.student)):
        _as(client, user, role)
        body = client.get(f"/api/billing/payments/{pid}").json()
        assert body["status"] == "paid"
        assert body["description"] == "100 credits"
        assert body["amountMinor"] == 10000
    assert client.get("/api/billing/payments/not-a-uuid").status_code == 422


def test_another_users_payment_is_indistinguishable_from_a_missing_one(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """IDOR: a viewer who is neither payer nor beneficiary gets the missing-id answer."""
    sm = migrated_sessionmaker
    owner = seed_user(sm)
    pid = seed_payment(
        sm,
        payer=owner,
        beneficiary=owner,
        pack_id=seed_pack(sm),
        status=PaymentStatus.paid,
        paid_at=FIXED_NOW,
    )
    for role_user in (seed_user(sm), seed_user(sm, Role.parent), seed_user(sm, Role.teacher)):
        _as(client, role_user, Role.student)
        foreign = client.get(f"/api/billing/payments/{pid}")
        missing = client.get(f"/api/billing/payments/{uuid.uuid4()}")
        assert (foreign.status_code, missing.status_code) == (404, 404)
        assert foreign.json() == missing.json()
        assert str(owner) not in foreign.text


# -- receipts -------------------------------------------------------------------


def test_receipts_list_only_payments_the_caller_paid(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    pack = seed_pack(sm)
    paid = seed_payment(
        sm,
        payer=parent,
        beneficiary=child,
        pack_id=pack,
        status=PaymentStatus.paid,
        paid_at=FIXED_NOW,
    )
    seed_payment(sm, payer=parent, beneficiary=child, pack_id=pack, status=PaymentStatus.created)
    seed_payment(sm, payer=parent, beneficiary=child, pack_id=pack, status=PaymentStatus.failed)

    _as(client, parent, Role.parent)
    receipts = client.get("/api/billing/receipts").json()["receipts"]
    assert [r["paymentId"] for r in receipts] == [str(paid)]
    assert receipts[0]["beneficiaryId"] == str(child)

    _as(client, child, Role.student)  # the beneficiary is not the payer: no receipts
    assert client.get("/api/billing/receipts").json()["receipts"] == []

    _as(client, seed_user(sm, Role.parent), Role.parent)  # IDOR: nor does a stranger
    assert client.get("/api/billing/receipts").json()["receipts"] == []


# -- saved cards (index R3, R21, R22) -----------------------------------------------


def _card(
    sm: sessionmaker[Session], user_id: uuid.UUID, *, token: str, pan: str, active: bool = True
) -> uuid.UUID:
    cipher = TokenCipher(TEST_CARD_TOKEN_KEY)
    card_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            SavedCard(
                id=card_id,
                user_id=user_id,
                token=cipher.encrypt(token, user_id),
                token_fingerprint=cipher.fingerprint(token, user_id),
                masked_pan=pan,
                brand="MasterCard",
                is_active=active,
            )
        )
    return card_id


def test_cards_list_only_the_callers_active_cards_masked(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    other = seed_user(sm, Role.parent)
    mine = _card(sm, parent, token="tok-parent-secret", pan="xxxx-xxxx-xxxx-2346")
    _card(sm, parent, token="tok-old", pan="xxxx-xxxx-xxxx-1111", active=False)
    _card(sm, other, token="tok-other-secret", pan="xxxx-xxxx-xxxx-9999")

    _as(client, parent, Role.parent)
    response = client.get("/api/billing/cards")
    assert response.status_code == 200
    assert response.json() == {
        "cards": [{"cardId": str(mine), "maskedPan": "xxxx-xxxx-xxxx-2346", "brand": "MasterCard"}]
    }
    assert "tok-" not in response.text  # neither plaintext nor ciphertext leaves the server
    assert "v1:" not in response.text

    _as(client, seed_user(sm), Role.student)  # IDOR: nobody else sees them
    assert client.get("/api/billing/cards").json() == {"cards": []}


def test_cards_never_expose_a_token_ciphertext_or_fingerprint(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    _card(sm, parent, token="tok-parent-secret", pan="xxxx-xxxx-xxxx-2346")
    with sm() as session:
        stored = session.scalars(sa.select(SavedCard)).one()
        ciphertext, fingerprint = stored.token, stored.token_fingerprint

    _as(client, parent, Role.parent)
    response = client.get("/api/billing/cards")
    body = response.json()
    assert all("token" not in key.lower() for key in _keys(body)), _keys(body)
    assert _keys(body) == {"cards", "cardId", "maskedPan", "brand"}
    for secret in ("tok-parent-secret", ciphertext, fingerprint):
        assert secret not in response.text


def test_a_saved_card_without_a_brand_is_an_empty_string(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    card_id = _card(sm, parent, token="tok-x", pan="xxxx-xxxx-xxxx-0001")
    with sm.begin() as session:
        card = session.get(SavedCard, card_id)
        assert card is not None
        card.brand = None
    _as(client, parent, Role.parent)
    assert client.get("/api/billing/cards").json()["cards"][0]["brand"] == ""
