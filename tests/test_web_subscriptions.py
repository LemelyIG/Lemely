"""Subscription routes and the Paymob subscription webhook (spec §5.1-§5.3, §6, §7; DV-21, DV-24).

Money and access safety: checkout is priced on the server and capped per user; a beneficiary, a
stranger and a teacher's assistant cannot change or cancel a plan they do not pay for (404, one
identical body, so the route is no existence oracle); the webhook refuses an unset secret (503,
never a body signed with the string ``"None"``), checks the HMAC before any database work, and
records a refused callback under kind ``subscription`` after the 401 has been sent.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from structlog.testing import capture_logs

from lemely.db import billing_observability_repo
from lemely.db.admin_health_repo import AdminHealthService
from lemely.db.models.billing import PaymobEvent, PaymobEventKind, PlanAudience, Subscription
from lemely.db.models.billing_ops import PaymobWebhookFailure
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.subscription_repo import (
    SUBSCRIPTION_WEBHOOK_PATH,
    GraceSettingMissing,
    SubscriptionError,
    SubscriptionService,
)
from lemely.io.paymob.client import PaymobError
from lemely.runtime.config import PaymobSettings, Settings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_settings
from lemely.web.deps_billing import (
    get_billing_sessionmaker,
    get_subscription_checkout_limiter,
    get_subscription_deps,
    get_subscription_webhook_limiter,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.routers import billing as billing_router
from lemely.web.routers import paymob_webhooks
from lemely.web.subscription_deps import SubscriptionDeps
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    ensure_billing_settings,
    link_parent,
    paymob_settings,
    remote_subscription,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    subscription_webhook,
    throwaway_database,
)
from tests.team_db import add_assistant, emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

BILLING = billing_router.router.prefix
WEBHOOK = paymob_webhooks.router.prefix + "/subscription"
PID = 4321
ACTING = "X-Lemely-Acting-Teacher"


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def pg_sessionmaker(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    ensure_billing_settings(_database)
    yield from emptied_after(_database)
    # Neither table references ``users``, so ``emptied_after``'s cascade does not reach them.
    with _database.begin() as session:
        session.execute(sa.text("TRUNCATE paymob_events, paymob_webhook_failures"))


@pytest.fixture(autouse=True)
def _fresh_failure_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure writer's cap is process-wide; give every test its own."""
    monkeypatch.setattr(
        billing_observability_repo, "_failure_cap", billing_observability_repo.FailureCap()
    )


class Harness:
    """An app over the throwaway database, a scripted Paymob and one signed-in user at a time."""

    def __init__(
        self,
        sm: sessionmaker[Session],
        *,
        settings: PaymobSettings | None = None,
        checkout_limit: int = 100,
        webhook_limit: int = 30,
    ) -> None:
        self.sm = sm
        self.fake = FakePaymobClient()
        self.paymob = settings or paymob_settings()
        self.app = create_app()
        full = Settings().model_copy(update={"paymob": self.paymob})
        self.app.dependency_overrides[get_settings] = lambda: full
        self.app.dependency_overrides[get_billing_sessionmaker] = lambda: sm
        deps = SubscriptionDeps(sm, self.fake, self.paymob)
        self.app.dependency_overrides[get_subscription_deps] = lambda: deps
        checkout = SlidingWindowLimiter(
            limit=checkout_limit, window_seconds=600, clock=time.monotonic
        )
        webhook = SlidingWindowLimiter(limit=webhook_limit, window_seconds=60, clock=time.monotonic)
        self.app.dependency_overrides[get_subscription_checkout_limiter] = lambda: checkout
        self.app.dependency_overrides[get_subscription_webhook_limiter] = lambda: webhook
        self.http = TestClient(self.app)

    def as_user(self, user_id: uuid.UUID, role: Role) -> TestClient:
        self.app.dependency_overrides[get_auth_context] = lambda: AuthContext(
            user_id=str(user_id), role=role.value
        )
        return self.http


def _error(response: Any) -> str:
    return str(response.json()["detail"]["error"])


def _events(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return len(session.scalars(sa.select(PaymobEvent)).all())


def _failures(sm: sessionmaker[Session]) -> list[tuple[str, str]]:
    with sm() as session:
        rows = session.scalars(sa.select(PaymobWebhookFailure)).all()
        return sorted((row.kind, row.reason) for row in rows)


def _teacher_with_plan(
    sm: sessionmaker[Session], *, seats: int = 0
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A teacher paying for a big plan with ``seats`` seated students: teacher, sub, big, small."""
    teacher = seed_user(sm, Role.teacher)
    big = seed_tier(sm, audience=PlanAudience.teacher, price_minor=50_000, included_seats=5)
    small = seed_tier(sm, audience=PlanAudience.teacher, price_minor=30_000, included_seats=1)
    sid = seed_subscription(
        sm,
        user_id=teacher,
        tier_id=big,
        payer_id=teacher,
        paymob_subscription_id=PID,
        paymob_amount_minor=50_000,
    )
    for _ in range(seats):
        seed_seat(sm, teacher_id=teacher, student_id=seed_user(sm, Role.student))
    return teacher, sid, big, small


def test_webhook_path_matches_the_plan_webhook_url() -> None:
    assert WEBHOOK == SUBSCRIPTION_WEBHOOK_PATH


# -- checkout --------------------------------------------------------------------------------


def test_checkout_creates_a_pending_subscription(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    http = Harness(pg_sessionmaker).as_user(student, Role.student)
    response = http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"subscriptionId", "paymentId", "checkoutUrl"}
    assert body["checkoutUrl"].startswith("https://")
    with pg_sessionmaker() as session:
        sub = session.get(Subscription, uuid.UUID(body["subscriptionId"]))
        assert sub is not None
        assert sub.status is SubscriptionStatus.pending_first_payment  # committed


def test_checkout_refuses_a_client_sent_price_and_extra_fields(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    http = Harness(pg_sessionmaker).as_user(student, Role.student)
    for extra in ({"priceMinor": 1}, {"extraSeats": -1}, {"extraSeats": 201}):
        response = http.post(
            f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)} | extra
        )
        assert response.status_code == 422, extra


def test_a_first_checkout_over_200_seats_reaches_the_admin_ceiling(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The schema no longer stops at 200: the service refuses above ``max_extra_seats``."""
    sm = pg_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    tier = seed_tier(sm, audience=PlanAudience.teacher, extra_seat_price_minor=100)
    http = Harness(sm).as_user(teacher, Role.teacher)
    url = f"{BILLING}/subscriptions/checkout"
    body = {"planTierId": str(tier), "extraSeats": 250}
    with sm.begin() as session:
        session.execute(sa.text("UPDATE billing_settings SET max_extra_seats = 200"))
    try:
        over = http.post(url, json=body)
        assert over.status_code == 422, over.text
        assert _error(over) == "invalid_extra_seats"  # the service's refusal, not a schema one
        with sm.begin() as session:
            session.execute(sa.text("UPDATE billing_settings SET max_extra_seats = 300"))
        allowed = http.post(url, json=body)
        assert allowed.status_code == 201, allowed.text
    finally:
        with sm.begin() as session:
            session.execute(sa.text("UPDATE billing_settings SET max_extra_seats = 200"))


def test_checkout_error_mapping(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    teacher_tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher)
    live_tier = seed_tier(pg_sessionmaker, paymob_plan_mode="live")
    h = Harness(pg_sessionmaker)
    url = f"{BILLING}/subscriptions/checkout"

    r = h.as_user(parent, Role.parent).post(
        url, json={"planTierId": str(tier), "beneficiaryId": str(child)}
    )
    assert (r.status_code, _error(r)) == (403, "not_linked_parent")
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    r = h.http.post(url, json={"planTierId": str(tier), "beneficiaryId": str(child)})
    assert r.status_code == 201

    http = h.as_user(student, Role.student)
    r = http.post(url, json={"planTierId": str(teacher_tier)})
    assert (r.status_code, _error(r)) == (422, "plan_not_purchasable")
    r = http.post(url, json={"planTierId": str(tier), "extraSeats": 1})
    assert (r.status_code, _error(r)) == (422, "invalid_extra_seats")
    r = http.post(url, json={"planTierId": str(live_tier)})
    assert (r.status_code, _error(r)) == (409, "plan_mode_mismatch")
    assert "message" in r.json()["detail"]
    seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student)
    r = http.post(url, json={"planTierId": str(tier)})
    assert (r.status_code, _error(r)) == (409, "already_subscribed")


def test_every_subscription_error_code_has_a_status() -> None:
    """A new ``SubscriptionError`` must be mapped on purpose, not fall through to 400."""
    pending = list(SubscriptionError.__subclasses__())
    codes: set[str] = set()
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        codes.add(cls.code)
    # Never reach these routes: the webhook parser, the credit-conversion helper and the plan sync.
    unreachable = {"subscription_error", "malformed_webhook", "no_credit_rate", "plan_sync_failed"}
    assert codes - unreachable <= set(billing_router._STATUS_FOR_CODE)


def test_checkout_answers_503_when_paymob_is_down(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    h = Harness(pg_sessionmaker)
    http = h.as_user(student, Role.student)
    good = h.fake.intention_response
    h.fake.intention_response = PaymobError("down")
    r = http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
    assert (r.status_code, _error(r)) == (503, "payments_unavailable")
    h.fake.intention_response = good
    r = http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
    assert r.status_code == 201  # the failed checkout does not block the retry


def test_a_missing_grace_setting_is_never_a_400_on_a_customer_route(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The routes turn every ``SubscriptionError`` into 4xx; a missing settings row must reach the
    app-level handler (503 with its code) even if a route ever reads the grace setting."""
    assert not issubclass(GraceSettingMissing, SubscriptionError)

    def missing(*_args: object, **_kwargs: object) -> None:
        raise GraceSettingMissing("Payments are temporarily unavailable")

    monkeypatch.setattr(SubscriptionService, "create_subscription_checkout", missing)
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    r = (
        Harness(pg_sessionmaker)
        .as_user(student, Role.student)
        .post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "grace_setting_missing"


def test_checkout_answers_503_when_paymob_is_unconfigured(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    h = Harness(pg_sessionmaker, settings=paymob_settings(secret_key=None))
    r = h.as_user(student, Role.student).post(
        f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)}
    )
    assert (r.status_code, _error(r)) == (503, "payments_unavailable")
    assert h.fake.intentions == []


def test_checkout_is_rate_limited_at_ten_per_user(pg_sessionmaker: sessionmaker[Session]) -> None:
    """The production provider's own limiter (10 per user per 600 s), not a test double."""
    student = seed_user(pg_sessionmaker, Role.student)
    other = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, is_active=False)
    h = Harness(pg_sessionmaker)
    get_subscription_checkout_limiter.cache_clear()
    del h.app.dependency_overrides[get_subscription_checkout_limiter]
    try:
        http = h.as_user(student, Role.student)
        for _ in range(10):
            r = http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
            assert r.status_code == 422
        r = http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) > 0
        assert _error(r) == "rate_limited"
        # Per user: someone else is unaffected.
        r = h.as_user(other, Role.student).post(
            f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)}
        )
        assert r.status_code == 422
    finally:
        get_subscription_checkout_limiter.cache_clear()


def test_a_parent_must_name_a_child_and_a_student_only_themselves(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    student = seed_user(pg_sessionmaker, Role.student)
    stranger = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    h = Harness(pg_sessionmaker)
    url = f"{BILLING}/subscriptions/checkout"
    assert (
        h.as_user(parent, Role.parent).post(url, json={"planTierId": str(tier)}).status_code == 422
    )
    r = h.as_user(student, Role.student).post(
        url, json={"planTierId": str(tier), "beneficiaryId": str(stranger)}
    )
    assert r.status_code == 403
    assert h.fake.intentions == []


def test_an_unknown_payer_token_is_403(pg_sessionmaker: sessionmaker[Session]) -> None:
    tier = seed_tier(pg_sessionmaker)
    h = Harness(pg_sessionmaker)
    r = h.as_user(uuid.uuid4(), Role.student).post(
        f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)}
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Billing is not available"


@pytest.mark.parametrize("role", [Role.platform_admin, Role.school_admin])
def test_admins_cannot_use_the_subscription_routes(
    pg_sessionmaker: sessionmaker[Session], role: Role
) -> None:
    admin = seed_user(pg_sessionmaker, role)
    tier = seed_tier(pg_sessionmaker)
    sid = uuid.uuid4()
    http = Harness(pg_sessionmaker).as_user(admin, role)
    assert (
        http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)}).status_code
        == 403
    )
    assert http.get(f"{BILLING}/subscriptions").status_code == 403
    assert http.post(f"{BILLING}/subscriptions/{sid}/cancel").status_code == 403
    r = http.post(f"{BILLING}/subscriptions/{sid}/downgrade", json={"planTierId": str(tier)})
    assert r.status_code == 403


# -- list ------------------------------------------------------------------------------------


def test_the_payer_and_the_child_beneficiary_see_a_parent_paid_plan(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    mine = seed_subscription(pg_sessionmaker, user_id=child, tier_id=tier, payer_id=parent)
    h = Harness(pg_sessionmaker)
    for user, role, is_payer in ((parent, Role.parent, True), (child, Role.student, False)):
        rows = h.as_user(user, role).get(f"{BILLING}/subscriptions").json()["subscriptions"]
        assert [(r["id"], r["isPayer"]) for r in rows] == [(str(mine), is_payer)]
    row = rows[0]
    assert row["beneficiaryUserId"] == str(child)
    assert row["planTierId"] == str(tier)
    assert set(row) == {
        "id",
        "beneficiaryUserId",
        "isPayer",
        "planTierId",
        "planCode",
        "planName",
        "status",
        "currentPeriodStart",
        "currentPeriodEnd",
        "graceUntil",
        "cancelAtPeriodEnd",
        "pendingPlanTierId",
        "extraSeats",
    }


def test_a_parent_does_not_see_a_childs_self_paid_plan_and_a_stranger_sees_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    stranger = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    seed_subscription(pg_sessionmaker, user_id=child, tier_id=tier, payer_id=child)
    h = Harness(pg_sessionmaker)
    for user, role in ((parent, Role.parent), (stranger, Role.student)):
        assert h.as_user(user, role).get(f"{BILLING}/subscriptions").json() == {"subscriptions": []}


def test_the_list_is_newest_first_and_hides_abandoned_checkouts(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    old = seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        status=SubscriptionStatus.expired,
        activated_at=T0,
        created_at=T0,
    )
    new = seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        created_at=T0 + timedelta(days=60),
    )
    seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        status=SubscriptionStatus.expired,
        created_at=T0 + timedelta(days=30),
    )
    rows = Harness(pg_sessionmaker).as_user(student, Role.student).get(f"{BILLING}/subscriptions")
    assert [r["id"] for r in rows.json()["subscriptions"]] == [str(new), str(old)]


# -- downgrade and cancel --------------------------------------------------------------------


def test_the_payer_downgrades_and_cancels(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher, sid, big, small = _teacher_with_plan(pg_sessionmaker, seats=1)
    http = Harness(pg_sessionmaker).as_user(teacher, Role.teacher)
    r = http.post(f"{BILLING}/subscriptions/{sid}/downgrade", json={"planTierId": str(small)})
    assert r.status_code == 200, r.text
    assert r.json()["pendingPlanTierId"] == str(small)
    assert r.json()["planTierId"] == str(big)
    assert r.json()["isPayer"] is True
    r = http.post(f"{BILLING}/subscriptions/{sid}/cancel")
    assert r.status_code == 200
    assert r.json()["cancelAtPeriodEnd"] is True
    with pg_sessionmaker() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        assert sub.cancel_at_period_end is True  # committed


def test_downgrade_error_mapping(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher, sid, big, small = _teacher_with_plan(pg_sessionmaker, seats=2)
    http = Harness(pg_sessionmaker).as_user(teacher, Role.teacher)
    r = http.post(f"{BILLING}/subscriptions/{sid}/downgrade", json={"planTierId": str(small)})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert (detail["error"], detail["inUse"], detail["capacity"]) == ("seats_insufficient", 2, 1)
    dearer = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, price_minor=90_000)
    r = http.post(f"{BILLING}/subscriptions/{sid}/downgrade", json={"planTierId": str(dearer)})
    assert (r.status_code, _error(r)) == (422, "invalid_plan_change")


def test_downgrade_unavailable_is_409(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher, sid, big, small = _teacher_with_plan(pg_sessionmaker)
    h = Harness(pg_sessionmaker, settings=paymob_settings(subscription_amount_updatable=False))
    r = h.as_user(teacher, Role.teacher).post(
        f"{BILLING}/subscriptions/{sid}/downgrade", json={"planTierId": str(small)}
    )
    assert (r.status_code, _error(r)) == (409, "downgrade_unavailable")


def test_only_the_payer_can_change_a_plan_and_everyone_else_gets_one_identical_404(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """IDOR: the beneficiary child, a stranger, an assistant and an unknown id are one answer."""
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    stranger = seed_user(pg_sessionmaker, Role.student)
    other_parent = seed_user(pg_sessionmaker, Role.parent)
    linked_not_payer = seed_user(pg_sessionmaker, Role.parent)
    link_parent(pg_sessionmaker, parent_id=linked_not_payer, child_id=child)
    lead = seed_user(pg_sessionmaker, Role.teacher)
    helper = seed_user(pg_sessionmaker, Role.teacher)
    add_assistant(pg_sessionmaker, teacher_id=lead, assistant_id=helper)
    big = seed_tier(
        pg_sessionmaker, audience=PlanAudience.teacher, price_minor=50_000, included_seats=5
    )
    small = seed_tier(
        pg_sessionmaker, audience=PlanAudience.teacher, price_minor=30_000, included_seats=1
    )
    student_tier = seed_tier(pg_sessionmaker)
    kids = seed_subscription(
        pg_sessionmaker,
        user_id=child,
        tier_id=student_tier,
        payer_id=parent,
        paymob_subscription_id=PID + 1,
    )
    leads = seed_subscription(
        pg_sessionmaker,
        user_id=lead,
        tier_id=big,
        payer_id=lead,
        paymob_subscription_id=PID,
        paymob_amount_minor=50_000,
    )
    h = Harness(pg_sessionmaker)

    bodies: list[Any] = []
    for sid, user, role, headers in (
        (kids, child, Role.student, {}),
        (kids, stranger, Role.student, {}),
        (leads, stranger, Role.teacher, {}),
        (leads, helper, Role.teacher, {ACTING: str(lead)}),
        (uuid.uuid4(), parent, Role.parent, {}),
        # Every role the routes admit, aimed at a subscription that EXISTS and is not theirs:
        # a parent unrelated to it, a parent linked to the child who is not the payer, and a
        # student or parent aimed at a teacher's plan.
        (kids, other_parent, Role.parent, {}),
        (kids, linked_not_payer, Role.parent, {}),
        (leads, other_parent, Role.parent, {}),
        (leads, stranger, Role.student, {}),
    ):
        http = h.as_user(user, role)
        for method, path, payload in (
            ("cancel", f"{BILLING}/subscriptions/{sid}/cancel", None),
            ("downgrade", f"{BILLING}/subscriptions/{sid}/downgrade", {"planTierId": str(small)}),
        ):
            r = http.post(path, json=payload, headers=headers)
            assert r.status_code == 404, (method, user, r.text)
            assert _error(r) == "subscription_not_found"
            bodies.append(r.json()["detail"]["message"].replace(str(sid), "<id>"))
    assert len(set(bodies)) == 1
    with pg_sessionmaker() as session:
        for sid in (kids, leads):
            sub = session.get(Subscription, sid)
            assert sub is not None
            assert (sub.cancel_at_period_end, sub.pending_plan_tier_id) == (False, None)


def test_a_manual_activation_cannot_be_cancelled_by_a_user(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    sid = seed_subscription(
        pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student, is_manually_activated=True
    )
    r = (
        Harness(pg_sessionmaker)
        .as_user(student, Role.student)
        .post(f"{BILLING}/subscriptions/{sid}/cancel")
    )
    assert (r.status_code, _error(r)) == (422, "invalid_plan_change")


@pytest.mark.parametrize("role", [Role.student, Role.parent, Role.teacher])
def test_the_cancel_route_never_reaches_the_system_cancel(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, role: Role
) -> None:
    """The system cancel has no payer check; no role the route admits may reach it.

    A student, a parent and a teacher each aim at a subscription that exists and belongs to
    someone else: the answer is the payer-checked 404 and the row is untouched.
    """
    owner = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, included_seats=5)
    sid = seed_subscription(
        pg_sessionmaker, user_id=owner, tier_id=tier, payer_id=owner, paymob_subscription_id=PID
    )
    actor = seed_user(pg_sessionmaker, role)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("schedule_cancel_as_system must not be reachable from a route")

    monkeypatch.setattr(SubscriptionService, "schedule_cancel_as_system", forbidden)
    r = Harness(pg_sessionmaker).as_user(actor, role).post(f"{BILLING}/subscriptions/{sid}/cancel")
    assert (r.status_code, _error(r)) == (404, "subscription_not_found")
    with pg_sessionmaker() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        assert sub.cancel_at_period_end is False


def test_the_payer_still_cancels_without_the_system_cancel(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher, sid, _, _ = _teacher_with_plan(pg_sessionmaker)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("schedule_cancel_as_system must not be reachable from a route")

    monkeypatch.setattr(SubscriptionService, "schedule_cancel_as_system", forbidden)
    http = Harness(pg_sessionmaker).as_user(teacher, Role.teacher)
    assert http.post(f"{BILLING}/subscriptions/{sid}/cancel").status_code == 200


# -- webhook ---------------------------------------------------------------------------------


def _cancelled_in_paymob(sm: sessionmaker[Session], sid: uuid.UUID) -> bool:
    """Whether a verified ``canceled`` callback was applied (UD-4 (b): cancel at period end)."""
    with sm() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        return sub.cancel_at_period_end and sub.paymob_cancelled_at is not None


def _paid_student(sm: sessionmaker[Session]) -> uuid.UUID:
    student = seed_user(sm, Role.student)
    return seed_subscription(
        sm,
        user_id=student,
        tier_id=seed_tier(sm),
        payer_id=student,
        paymob_subscription_id=PID,
        paymob_amount_minor=10_000,
    )


def test_webhook_applies_a_verified_callback_after_commit(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _paid_student(pg_sessionmaker)
    h = Harness(pg_sessionmaker)
    h.fake.subscriptions[PID] = remote_subscription(PID, state="canceled")
    r = h.http.post(WEBHOOK, json=subscription_webhook("canceled", PID))
    assert (r.status_code, r.json()) == (200, {"status": "ok"})
    assert _cancelled_in_paymob(pg_sessionmaker, sid)


def test_a_duplicate_delivery_is_a_200_no_op(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _paid_student(pg_sessionmaker)
    h = Harness(pg_sessionmaker)
    h.fake.subscriptions[PID] = remote_subscription(PID, state="canceled")
    body = subscription_webhook("canceled", PID, paymob_request_id="r-1")
    assert h.http.post(WEBHOOK, json=body).status_code == 200
    events = _events(pg_sessionmaker)
    assert h.http.post(WEBHOOK, json=body).json() == {"status": "ok"}
    assert _events(pg_sessionmaker) == events
    assert _cancelled_in_paymob(pg_sessionmaker, sid)


def test_a_forged_hmac_is_401_and_stores_no_event(pg_sessionmaker: sessionmaker[Session]) -> None:
    h = Harness(pg_sessionmaker)
    forged = subscription_webhook("Successful Transaction", PID, secret="wrong")
    with capture_logs() as logs:
        assert h.http.post(WEBHOOK, json=forged).status_code == 401
    tampered = subscription_webhook("canceled", PID)
    tampered["trigger_type"] = "Successful Transaction"  # the HMAC binds the trigger
    assert h.http.post(WEBHOOK, json=tampered).status_code == 401
    missing = subscription_webhook("canceled", PID)
    del missing["hmac"]
    assert h.http.post(WEBHOOK, json=missing).status_code == 401
    non_string = subscription_webhook("canceled", PID) | {"hmac": 5}
    assert h.http.post(WEBHOOK, json=non_string).status_code == 401
    assert _events(pg_sessionmaker) == 0
    assert h.fake.calls == []
    (event,) = [e for e in logs if e["event"] == "paymob_subscription_hmac_mismatch"]
    assert event["log_level"] == "error"
    assert event["paymob_subscription_id"] == PID
    assert event["trigger_type"] == "Successful Transaction"
    assert "wrong" not in repr(logs)
    assert forged["hmac"] not in repr(logs)


def test_the_mismatch_log_names_only_a_known_trigger(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The trigger of an unauthenticated body is attacker text: it is logged only if known."""
    h = Harness(pg_sessionmaker)
    with capture_logs() as logs:
        for trigger in ("suspended", "evil\nINJECTED " + "x" * 80):
            forged = subscription_webhook(trigger, PID, secret="wrong")
            assert h.http.post(WEBHOOK, json=forged).status_code == 401
    seen = [e["trigger_type"] for e in logs if e["event"] == "paymob_subscription_hmac_mismatch"]
    assert seen == ["suspended", "unknown"]
    assert "INJECTED" not in repr(logs)


def test_the_hmac_is_checked_before_any_database_work(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins "HMAC before any DB work": a service built before verification is a 500, not a 401."""

    def boom(self: SubscriptionDeps, session: Session) -> SubscriptionService:
        raise AssertionError("the service was built before the HMAC was verified")

    monkeypatch.setattr(SubscriptionDeps, "service", boom)
    h = Harness(pg_sessionmaker)
    forged = subscription_webhook("Successful Transaction", PID, secret="wrong")
    assert h.http.post(WEBHOOK, json=forged).status_code == 401


def test_a_forged_callback_checks_out_no_database_connection_to_decide_the_401(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any DB access before the HMAC check (a read, a lock, a session) takes a pool checkout.

    The after-response failure row is stubbed out, since it is the one write that follows the 401.
    """
    monkeypatch.setattr(paymob_webhooks, "record_webhook_failure", lambda sm, **kw: True)
    checkouts: list[str] = []
    engine = pg_sessionmaker.kw["bind"]

    def on_checkout(*args: object) -> None:
        checkouts.append("checkout")

    def on_execute(*args: object) -> None:
        checkouts.append("execute")

    sa_event.listen(engine, "checkout", on_checkout)
    sa_event.listen(engine, "before_cursor_execute", on_execute)
    try:
        h = Harness(pg_sessionmaker)
        for trigger in ("Successful Transaction", "canceled", "suspended"):
            forged = subscription_webhook(trigger, PID, secret="wrong")
            assert h.http.post(WEBHOOK, json=forged).status_code == 401
        missing = subscription_webhook("canceled", PID)
        del missing["hmac"]
        assert h.http.post(WEBHOOK, json=missing).status_code == 401
    finally:
        sa_event.remove(engine, "checkout", on_checkout)
        sa_event.remove(engine, "before_cursor_execute", on_execute)
    assert checkouts == []


def test_a_refused_callback_is_recorded_as_kind_subscription_after_the_401(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    h = Harness(pg_sessionmaker)
    assert (
        h.http.post(WEBHOOK, json=subscription_webhook("canceled", PID, secret="wrong")).status_code
        == 401
    )
    missing = subscription_webhook("canceled", PID)
    del missing["hmac"]
    assert h.http.post(WEBHOOK, json=missing).status_code == 401
    assert _failures(pg_sessionmaker) == [
        ("subscription", "hmac_mismatch"),
        ("subscription", "hmac_missing"),
    ]


def test_admin_health_counts_a_refused_subscription_callback(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The health screen's HMAC-failure count is not limited to the transaction and token kinds."""
    h = Harness(pg_sessionmaker)
    assert (
        h.http.post(WEBHOOK, json=subscription_webhook("canceled", PID, secret="wrong")).status_code
        == 401
    )
    report = AdminHealthService(pg_sessionmaker).health(hours=1)
    assert report.hmac_failures == 1


def test_the_failure_row_is_a_background_task_and_never_changes_the_401(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from fastapi import Request

    seen: list[str] = []
    monkeypatch.setattr(
        paymob_webhooks, "record_webhook_failure", lambda sm, **kw: seen.append(kw["kind"]) or True
    )
    h = Harness(pg_sessionmaker)
    deps = SubscriptionDeps(pg_sessionmaker, h.fake, h.paymob)
    forged = subscription_webhook("canceled", PID, secret="wrong")
    request = Request({"type": "http", "headers": [], "client": ("9.9.9.9", 1)})
    response = paymob_webhooks.paymob_subscription_webhook(
        request,
        h.paymob.hmac_secret.get_secret_value(),  # type: ignore[union-attr]
        forged,
        deps,
        SlidingWindowLimiter(limit=30, window_seconds=60, clock=time.monotonic),
    )
    assert response.status_code == 401  # type: ignore[union-attr]
    assert response.body == b'{"detail":"HMAC verification failed"}'  # type: ignore[union-attr]
    assert seen == []  # nothing is written while the response is being decided
    asyncio.run(response.background())  # type: ignore[union-attr]
    assert seen == ["subscription"]

    def refuses(sm: object, **kw: object) -> bool:
        raise RuntimeError("database down")

    monkeypatch.setattr(paymob_webhooks, "record_webhook_failure", refuses)
    assert (
        h.http.post(WEBHOOK, json=forged).status_code == 401
    )  # an unrecordable failure is still a 401


def test_an_unset_secret_is_503_even_for_a_body_signed_with_the_string_none(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _paid_student(pg_sessionmaker)
    h = Harness(pg_sessionmaker, settings=paymob_settings(hmac_secret=None))
    h.fake.subscriptions[PID] = remote_subscription(PID, state="canceled")
    body = subscription_webhook("canceled", PID, secret="None")
    r = h.http.post(WEBHOOK, json=body)
    assert r.status_code == 503
    assert not _cancelled_in_paymob(pg_sessionmaker, sid)
    assert _events(pg_sessionmaker) == 0
    assert h.fake.calls == []


def test_a_body_over_64_kib_is_413_before_anything_else(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    h = Harness(pg_sessionmaker)
    padded = subscription_webhook("canceled", PID) | {"padding": "x" * (64 * 1024)}
    assert h.http.post(WEBHOOK, json=padded).status_code == 413
    assert _failures(pg_sessionmaker) == []


def test_malformed_bodies_are_400(pg_sessionmaker: sessionmaker[Session]) -> None:
    h = Harness(pg_sessionmaker)
    assert h.http.post(WEBHOOK, content=b"not json").status_code == 400
    assert h.http.post(WEBHOOK, json=[1, 2]).status_code == 400
    no_id = {"trigger_type": "canceled", "subscription_data": {}, "hmac": "x"}
    assert h.http.post(WEBHOOK, json=no_id).status_code == 400
    assert h.http.post(WEBHOOK, json={"trigger_type": "x"}).status_code == 400
    assert h.fake.calls == []
    assert _failures(pg_sessionmaker) == []  # a malformed body is not a signature failure


def test_the_service_rejecting_a_signed_body_as_malformed_is_400(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from lemely.db.subscription_repo import MalformedWebhook

    def malformed(self: SubscriptionService, body: object, *, now: object) -> None:
        raise MalformedWebhook("bad")

    monkeypatch.setattr(SubscriptionService, "apply_renewal_webhook", malformed)
    h = Harness(pg_sessionmaker)
    with capture_logs() as logs:
        r = h.http.post(WEBHOOK, json=subscription_webhook("canceled", PID))
    assert r.status_code == 400
    (event,) = [e for e in logs if e["event"] == "paymob_subscription_webhook_malformed"]
    assert event["alert"] is True  # a signed body we cannot read is a Paymob format change


def test_paymob_down_is_503_and_nothing_is_stored_so_the_retry_is_processed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _paid_student(pg_sessionmaker)
    h = Harness(pg_sessionmaker)
    h.fake.fail["get_subscription"] = PaymobError("down")
    body = subscription_webhook("canceled", PID, paymob_request_id="r-1")
    assert h.http.post(WEBHOOK, json=body).status_code == 503
    assert _events(pg_sessionmaker) == 0
    assert not _cancelled_in_paymob(pg_sessionmaker, sid)
    h.fake.fail.clear()
    h.fake.subscriptions[PID] = remote_subscription(PID, state="canceled")
    assert h.http.post(WEBHOOK, json=body).status_code == 200
    assert _cancelled_in_paymob(pg_sessionmaker, sid)


def test_an_unexpected_failure_is_500_with_no_message_echo_and_rolls_back(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(self: SubscriptionService, body: object, *, now: object) -> None:
        self._session.add(
            PaymobEvent(  # a write the failure must roll back
                kind=PaymobEventKind.subscription, dedupe_key="rolled-back", payload={}
            )
        )
        self._session.flush()
        raise RuntimeError("secret-driver-detail: password=hunter2")

    monkeypatch.setattr(SubscriptionService, "apply_renewal_webhook", explode)
    h = Harness(pg_sessionmaker)
    with capture_logs() as logs:
        r = h.http.post(WEBHOOK, json=subscription_webhook("canceled", PID))
    assert r.status_code == 500
    assert "hunter2" not in r.text
    assert "hunter2" not in repr(logs)
    (event,) = [e for e in logs if e["event"] == "paymob_subscription_webhook_failed"]
    assert event["error_type"] == "RuntimeError"
    assert event["alert"] is True
    assert _events(pg_sessionmaker) == 0


def test_a_paymob_failure_is_logged_by_type_only(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _paid_student(pg_sessionmaker)
    h = Harness(pg_sessionmaker)
    h.fake.fail["get_subscription"] = PaymobError("token=abc123 leaked")
    with capture_logs() as logs:
        r = h.http.post(WEBHOOK, json=subscription_webhook("canceled", PID))
    assert r.status_code == 503
    assert "abc123" not in r.text
    assert "abc123" not in repr(logs)
    (event,) = [e for e in logs if e["event"] == "paymob_subscription_webhook_deferred"]
    assert event["error_type"] == "PaymobError"
    assert "alert" not in event  # Paymob being down is retried by Paymob; a rate alert watches it


def test_the_thirty_first_delivery_for_one_id_in_a_minute_is_429(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The production provider's own limiter (30 per Paymob subscription id per 60 s)."""
    h = Harness(pg_sessionmaker)
    get_subscription_webhook_limiter.cache_clear()
    del h.app.dependency_overrides[get_subscription_webhook_limiter]
    try:
        h.fake.subscriptions[PID] = remote_subscription(PID, state="canceled")
        for n in range(30):
            body = subscription_webhook("canceled", PID, paymob_request_id=f"r-{n}")
            assert h.http.post(WEBHOOK, json=body).status_code == 200
        with capture_logs() as logs:
            r = h.http.post(WEBHOOK, json=subscription_webhook("canceled", PID))
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) > 0
        (event,) = [e for e in logs if e["event"] == "paymob_subscription_webhook_rate_limited"]
        assert event["log_level"] == "warning"
        assert event["paymob_subscription_id"] == PID
        assert event["trigger_type"] == "canceled"
        # Per subscription id: another id is unaffected.
        assert (
            h.http.post(WEBHOOK, json=subscription_webhook("canceled", PID + 1)).status_code == 200
        )
    finally:
        get_subscription_webhook_limiter.cache_clear()


def test_forged_deliveries_do_not_burn_a_real_ids_limit(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The limiter runs after the HMAC, so an unauthenticated caller cannot lock Paymob out."""
    h = Harness(pg_sessionmaker, webhook_limit=2)
    h.fake.subscriptions[PID] = remote_subscription(PID, state="canceled")
    forged = subscription_webhook("canceled", PID, secret="wrong")
    for _ in range(5):
        assert h.http.post(WEBHOOK, json=forged).status_code == 401
    assert h.http.post(WEBHOOK, json=subscription_webhook("canceled", PID)).status_code == 200
