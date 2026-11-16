"""GET /api/billing/summary: plan, period, meter, credits, debt, seats (index R3, spec §2.1, §7)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.db.models import ParentChildLink
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    SavedCard,
    Subscription,
)
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.usage import GrantKind, UsageDebt
from lemely.runtime.config import PaymobSettings, Settings
from lemely.web import create_app
from lemely.web.deps import ACTING_TEACHER_HEADER, AuthContext, get_auth_context, get_settings
from lemely.web.deps_billing import get_billing_sessionmaker
from lemely.web.routers.billing import get_billing_clock
from lemely.web.usage import get_usage_meter
from tests.subscription_fixtures import edit_tier_terms, ensure_billing_settings
from tests.team_db import add_assistant, add_seat, add_user, emptied_after, team_database
from tests.usage_helpers import NOW, enforcing_meter, give

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

URL = "/api/billing/summary"
HEADER = ACTING_TEACHER_HEADER


@pytest.fixture(scope="module")
def summary_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(summary_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(summary_db)


def _client(sm: sessionmaker[Session], user: uuid.UUID, role: Role) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_billing_sessionmaker] = lambda: sm
    app.dependency_overrides[get_billing_clock] = lambda: lambda: NOW
    app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(sm)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(user), role=role.value
    )
    return TestClient(app)


def _link(sm: sessionmaker[Session], parent: uuid.UUID, child: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=child))


def _tier(
    sm: sessionmaker[Session],
    *,
    audience: PlanAudience = PlanAudience.student,
    included_seats: int = 0,
    extra_seat_price_minor: int = 0,
    price_minor: int = 9_900,
) -> uuid.UUID:
    tier_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            PlanTier(
                id=tier_id,
                code=f"tier_{tier_id.hex[:8]}",
                name=f"Plan {tier_id.hex[:4]}",
                price_minor=price_minor,
                interval=PlanInterval.monthly,
                audience=audience,
                allowance_units=1_000,
                included_seats=included_seats,
                seat_allowance_units=100,
                extra_seat_price_minor=extra_seat_price_minor,
                is_active=True,
            )
        )
    return tier_id


def _sub(
    sm: sessionmaker[Session],
    *,
    user: uuid.UUID,
    tier: uuid.UUID,
    payer: uuid.UUID | None,
    status: SubscriptionStatus = SubscriptionStatus.active,
    extra_seats: int = 0,
    pending_tier: uuid.UUID | None = None,
    pending_extra_seats: int | None = None,
    grace_until: datetime | None = None,
    cancel_at_period_end: bool = False,
    created_at: datetime = NOW - timedelta(days=5),
) -> uuid.UUID:
    sub_id = uuid.uuid4()
    with sm.begin() as session:
        sub = Subscription(
            id=sub_id,
            user_id=user,
            payer_user_id=payer,
            plan_tier_id=tier,
            status=status,
            extra_seats=extra_seats,
            pending_plan_tier_id=pending_tier,
            pending_extra_seats=pending_extra_seats,
            grace_until=grace_until,
            cancel_at_period_end=cancel_at_period_end,
            current_period_start=NOW - timedelta(days=5),
            current_period_end=NOW + timedelta(days=25),
            is_manually_activated=payer is None,
        )
        sub.created_at = created_at
        session.add(sub)
    return sub_id


def _first_payment(
    sm: sessionmaker[Session],
    *,
    sub: uuid.UUID,
    payer: uuid.UUID,
    beneficiary: uuid.UUID,
    tier: uuid.UUID,
    status: PaymentStatus,
    created_at: datetime = NOW - timedelta(minutes=5),
) -> uuid.UUID:
    payment_id = uuid.uuid4()
    with sm.begin() as session:
        payment = Payment(
            id=payment_id,
            payer_user_id=payer,
            beneficiary_user_id=beneficiary,
            purpose=PaymentPurpose.subscription_first,
            plan_tier_id=tier,
            subscription_id=sub,
            amount_minor=9_900,
            currency="EGP",
            status=status,
            special_reference=str(payment_id),
        )
        payment.created_at = created_at
        session.add(payment)
    return payment_id


def _card(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    pan: str,
    *,
    brand: str = "Visa",
    is_active: bool = True,
    created_at: datetime = NOW - timedelta(days=10),
) -> None:
    with sm.begin() as session:
        card = SavedCard(
            user_id=user,
            token="ciphertext",
            token_fingerprint=uuid.uuid4().hex * 2,
            masked_pan=pan,
            brand=brand,
            is_active=is_active,
        )
        card.created_at = created_at
        session.add(card)


def _debt(sm: sessionmaker[Session], owner: uuid.UUID, units: int) -> None:
    with sm.begin() as session:
        session.add(UsageDebt(owner_user_id=owner, job_id=None, units=units, outstanding=units))


def _in_days(days: int) -> datetime:
    return NOW + timedelta(days=days)


# --- the student's own summary ---------------------------------------------------------------


def test_student_summary_has_plan_meter_credits_debt_and_card(
    sm: sessionmaker[Session],
) -> None:
    student = add_user(sm, Role.student, display_name="Sara Ali")
    tier = _tier(sm)
    sid = _sub(sm, user=student, tier=tier, payer=student)
    give(
        sm,
        student,
        units=1_000,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_in_days(25),
    )
    give(sm, student, units=500, expires_at=_in_days(365))
    give(sm, student, units=200, expires_at=_in_days(90))
    _card(sm, student, "xxxx-xxxx-xxxx-2346", brand="MasterCard")
    _debt(sm, student, 40)

    body = _client(sm, student, Role.student).get(URL).json()

    assert body["beneficiary"] == {
        "userId": str(student),
        "displayName": "Sara Ali",
        "audience": "student",
    }
    assert body["subscription"]["subscriptionId"] == str(sid)
    assert body["subscription"]["tier"]["planTierId"] == str(tier)
    assert body["subscription"]["status"] == "active"
    assert body["subscription"]["pendingTier"] is None
    assert (body["canManage"], body["managedByName"]) == (True, None)
    assert body["savedCard"]["maskedPan"] == "xxxx-xxxx-xxxx-2346"
    assert body["savedCard"]["brand"] == "MasterCard"
    assert body["usage"]["fraction"] == 0.0  # allowance granted, nothing spent
    assert body["usage"]["resetsAt"] is not None
    # Soonest expiry first. The allowance is not a credit.
    assert [(e["units"], e["expiresAt"][:10]) for e in body["credits"]["expiring"]] == [
        (200, _in_days(90).date().isoformat()),
        (500, _in_days(365).date().isoformat()),
    ]
    assert body["credits"]["totalUnits"] == 700
    assert body["debtUnits"] == 40
    assert body["seats"] is None


def test_usage_credits_and_debt_equal_the_usage_meter(sm: sessionmaker[Session]) -> None:
    """Same numbers as ``GET /api/usage/meter``: hidden signup grant, shared expiry, no expiry."""
    student = add_user(sm, Role.student)
    shared_expiry = _in_days(60)
    give(
        sm,
        student,
        units=1_000,
        kind=GrantKind.period_allowance,
        visible=False,
        expires_at=_in_days(25),
    )
    give(sm, student, units=300, expires_at=shared_expiry)
    give(sm, student, units=120, expires_at=shared_expiry)
    give(sm, student, units=75, expires_at=None)
    give(sm, student, units=50, kind=GrantKind.signup, visible=False, expires_at=_in_days(30))
    _debt(sm, student, 12)

    client = _client(sm, student, Role.student)
    summary = client.get(URL).json()
    meter = client.get("/api/usage/meter").json()

    assert summary["usage"] == {
        "fraction": meter["allowanceFraction"],
        "resetsAt": meter["allowanceResetsAt"],
    }
    assert summary["credits"]["totalUnits"] == meter["creditsBalance"]
    assert summary["credits"]["totalUnits"] == 300 + 120 + 75 + 50
    assert summary["debtUnits"] == meter["debtUnits"]
    by_expiry: dict[str | None, int] = {}
    for lot in meter["creditLots"]:
        by_expiry[lot["expiresAt"]] = by_expiry.get(lot["expiresAt"], 0) + lot["remaining"]
    expiring = summary["credits"]["expiring"]
    assert {e["expiresAt"]: e["units"] for e in expiring} == by_expiry
    assert len(expiring) == len(by_expiry)  # the two lots sharing an expiry are one row
    assert expiring[-1] == {"units": 75, "expiresAt": None}  # no expiry sorts last


# --- which subscription is shown ---------------------------------------------------------------


def test_no_subscription_means_null_and_may_buy(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    body = _client(sm, student, Role.student).get(URL).json()
    assert body["subscription"] is None
    assert body["canManage"] is True
    assert body["savedCard"] is None
    assert body["credits"] == {"totalUnits": 0, "expiring": []}
    assert (body["debtUnits"], body["usage"]["fraction"]) == (0, None)


@pytest.mark.parametrize(
    "ended",
    [SubscriptionStatus.expired, SubscriptionStatus.cancelled, SubscriptionStatus.inactive],
)
def test_an_ended_subscription_is_not_shown(
    sm: sessionmaker[Session], ended: SubscriptionStatus
) -> None:
    student = add_user(sm, Role.student)
    _sub(sm, user=student, tier=_tier(sm), payer=student, status=ended)
    body = _client(sm, student, Role.student).get(URL).json()
    assert body["subscription"] is None
    assert body["canManage"] is True


def test_a_past_due_subscription_is_shown_with_its_grace_and_pending_changes(
    sm: sessionmaker[Session],
) -> None:
    student = add_user(sm, Role.student)
    current, cheaper = _tier(sm), _tier(sm, price_minor=4_900)
    grace = _in_days(2)
    _sub(
        sm,
        user=student,
        tier=current,
        payer=student,
        status=SubscriptionStatus.past_due,
        grace_until=grace,
        pending_tier=cheaper,
        pending_extra_seats=0,
        cancel_at_period_end=True,
    )
    sub = _client(sm, student, Role.student).get(URL).json()["subscription"]
    assert sub["status"] == "past_due"
    assert sub["graceUntil"][:10] == grace.date().isoformat()
    assert sub["pendingTier"]["planTierId"] == str(cheaper)
    assert sub["pendingExtraSeats"] == 0
    assert sub["cancelAtPeriodEnd"] is True


def test_an_open_first_checkout_is_shown_as_pending(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    tier = _tier(sm)
    sid = _sub(
        sm, user=student, tier=tier, payer=student, status=SubscriptionStatus.pending_first_payment
    )
    _first_payment(
        sm, sub=sid, payer=student, beneficiary=student, tier=tier, status=PaymentStatus.created
    )
    sub = _client(sm, student, Role.student).get(URL).json()["subscription"]
    assert sub["subscriptionId"] == str(sid)
    assert sub["status"] == "pending_first_payment"


def test_a_stale_pending_checkout_is_not_shown(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    tier = _tier(sm)
    sid = _sub(
        sm, user=student, tier=tier, payer=student, status=SubscriptionStatus.pending_first_payment
    )
    _first_payment(
        sm, sub=sid, payer=student, beneficiary=student, tier=tier, status=PaymentStatus.failed
    )
    body = _client(sm, student, Role.student).get(URL).json()
    assert body["subscription"] is None
    assert body["canManage"] is True


def test_the_newest_first_payment_decides_whether_a_pending_checkout_is_open(
    sm: sessionmaker[Session],
) -> None:
    student = add_user(sm, Role.student)
    tier = _tier(sm)
    sid = _sub(
        sm, user=student, tier=tier, payer=student, status=SubscriptionStatus.pending_first_payment
    )
    _first_payment(
        sm,
        sub=sid,
        payer=student,
        beneficiary=student,
        tier=tier,
        status=PaymentStatus.failed,
        created_at=NOW - timedelta(hours=2),
    )
    _first_payment(
        sm,
        sub=sid,
        payer=student,
        beneficiary=student,
        tier=tier,
        status=PaymentStatus.pending,
        created_at=NOW - timedelta(minutes=1),
    )
    sub = _client(sm, student, Role.student).get(URL).json()["subscription"]
    assert sub["status"] == "pending_first_payment"


def test_the_newest_of_two_open_checkouts_is_reported(sm: sessionmaker[Session]) -> None:
    """Two open checkouts can coexist only without a payer (the live index covers paid rows)."""
    student = add_user(sm, Role.student)
    tier = _tier(sm)
    older = _sub(
        sm,
        user=student,
        tier=tier,
        payer=None,
        status=SubscriptionStatus.pending_first_payment,
        created_at=NOW - timedelta(hours=3),
    )
    newer = _sub(
        sm,
        user=student,
        tier=tier,
        payer=None,
        status=SubscriptionStatus.pending_first_payment,
        created_at=NOW - timedelta(hours=1),
    )
    for sub in (older, newer):
        _first_payment(
            sm, sub=sub, payer=student, beneficiary=student, tier=tier, status=PaymentStatus.created
        )
    sub = _client(sm, student, Role.student).get(URL).json()["subscription"]
    assert sub["subscriptionId"] == str(newer)


def test_a_live_plan_wins_over_a_pending_checkout(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    tier = _tier(sm)
    live = _sub(sm, user=student, tier=tier, payer=None)  # a manual activation
    pending = _sub(
        sm, user=student, tier=tier, payer=student, status=SubscriptionStatus.pending_first_payment
    )
    _first_payment(
        sm, sub=pending, payer=student, beneficiary=student, tier=tier, status=PaymentStatus.created
    )
    sub = _client(sm, student, Role.student).get(URL).json()["subscription"]
    assert sub["subscriptionId"] == str(live)


def test_a_manual_activation_is_shown_but_nobody_manages_it(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    _card(sm, student, "xxxx-xxxx-xxxx-1111")
    sid = _sub(sm, user=student, tier=_tier(sm), payer=None)
    body = _client(sm, student, Role.student).get(URL).json()
    assert body["subscription"]["subscriptionId"] == str(sid)
    assert (body["canManage"], body["managedByName"], body["savedCard"]) == (False, None, None)


# --- who manages it ----------------------------------------------------------------------------


def test_parent_pays_for_child_and_each_sees_their_part(sm: sessionmaker[Session]) -> None:
    parent = add_user(sm, Role.parent, display_name="Mona Hassan")
    child = add_user(sm, Role.student, display_name="Omar Hassan")
    _link(sm, parent, child)
    _card(sm, parent, "xxxx-xxxx-xxxx-0001")
    _card(sm, child, "xxxx-xxxx-xxxx-0002")
    _sub(sm, user=child, tier=_tier(sm), payer=parent)

    as_parent = _client(sm, parent, Role.parent).get(URL, params={"beneficiaryId": str(child)})
    assert as_parent.status_code == 200
    seen = as_parent.json()
    assert seen["beneficiary"]["userId"] == str(child)
    assert (seen["canManage"], seen["managedByName"]) == (True, None)
    assert seen["savedCard"]["maskedPan"] == "xxxx-xxxx-xxxx-0001"

    as_child = _client(sm, child, Role.student).get(URL).json()
    assert as_child["subscription"] is not None
    assert (as_child["canManage"], as_child["managedByName"]) == (False, "Mona Hassan")
    assert as_child["savedCard"] is None  # never the parent's card, nor their own here


def test_a_parent_viewing_a_childs_self_paid_plan_manages_nothing(
    sm: sessionmaker[Session],
) -> None:
    parent = add_user(sm, Role.parent, display_name="Mona Hassan")
    child = add_user(sm, Role.student, display_name="Omar Hassan")
    _link(sm, parent, child)
    _card(sm, parent, "xxxx-xxxx-xxxx-0001")
    _card(sm, child, "xxxx-xxxx-xxxx-0002")
    _sub(sm, user=child, tier=_tier(sm), payer=child)

    body = _client(sm, parent, Role.parent).get(URL, params={"beneficiaryId": str(child)}).json()

    assert body["subscription"] is not None
    assert body["canManage"] is False
    assert body["savedCard"] is None  # neither the child's card nor the parent's
    assert body["managedByName"] == "Omar Hassan"


def test_a_parent_starting_a_plan_sees_their_own_card_not_the_childs(
    sm: sessionmaker[Session],
) -> None:
    parent = add_user(sm, Role.parent)
    child = add_user(sm, Role.student)
    _link(sm, parent, child)
    _card(sm, parent, "xxxx-xxxx-xxxx-0001")
    _card(sm, child, "xxxx-xxxx-xxxx-0002")
    body = _client(sm, parent, Role.parent).get(URL, params={"beneficiaryId": str(child)}).json()
    assert body["subscription"] is None
    assert body["canManage"] is True
    # No plan yet: the caller would be the payer, so the card is the caller's own.
    assert body["savedCard"]["maskedPan"] == "xxxx-xxxx-xxxx-0001"


def test_the_newest_active_card_is_shown_and_an_inactive_one_never_is(
    sm: sessionmaker[Session],
) -> None:
    student = add_user(sm, Role.student)
    _sub(sm, user=student, tier=_tier(sm), payer=student)
    _card(sm, student, "xxxx-xxxx-xxxx-0001", created_at=NOW - timedelta(days=30))
    _card(sm, student, "xxxx-xxxx-xxxx-0002", created_at=NOW - timedelta(days=3))
    _card(sm, student, "xxxx-xxxx-xxxx-0003", is_active=False, created_at=NOW - timedelta(days=1))
    client = _client(sm, student, Role.student)
    assert client.get(URL).json()["savedCard"]["maskedPan"] == "xxxx-xxxx-xxxx-0002"

    only_inactive = add_user(sm, Role.student)
    _card(sm, only_inactive, "xxxx-xxxx-xxxx-0004", is_active=False)
    body = _client(sm, only_inactive, Role.student).get(URL).json()
    assert body["savedCard"] is None


# --- access (object level) ---------------------------------------------------------------------


def test_a_parent_must_name_a_child(sm: sessionmaker[Session]) -> None:
    parent = add_user(sm, Role.parent)
    assert _client(sm, parent, Role.parent).get(URL).status_code == 422


def test_a_parent_cannot_view_an_unlinked_student(sm: sessionmaker[Session]) -> None:
    parent = add_user(sm, Role.parent)
    stranger = add_user(sm, Role.student)
    _sub(sm, user=stranger, tier=_tier(sm), payer=stranger)
    response = _client(sm, parent, Role.parent).get(URL, params={"beneficiaryId": str(stranger)})
    assert response.status_code == 403
    assert "linked child" in response.json()["detail"]


def test_a_parent_cannot_view_a_linked_user_who_is_not_a_student(
    sm: sessionmaker[Session],
) -> None:
    parent = add_user(sm, Role.parent)
    teacher = add_user(sm, Role.teacher)
    _link(sm, parent, teacher)
    response = _client(sm, parent, Role.parent).get(URL, params={"beneficiaryId": str(teacher)})
    assert response.status_code == 403


def test_a_parent_cannot_name_themselves(sm: sessionmaker[Session]) -> None:
    parent = add_user(sm, Role.parent)
    response = _client(sm, parent, Role.parent).get(URL, params={"beneficiaryId": str(parent)})
    assert response.status_code == 403


@pytest.mark.parametrize("role", [Role.student, Role.teacher])
def test_a_student_or_teacher_cannot_name_someone_else(
    sm: sessionmaker[Session], role: Role
) -> None:
    caller = add_user(sm, role)
    other = add_user(sm, Role.student)
    client = _client(sm, caller, role)
    assert client.get(URL, params={"beneficiaryId": str(other)}).status_code == 403
    assert client.get(URL, params={"beneficiaryId": str(caller)}).status_code == 200


@pytest.mark.parametrize("role", [Role.platform_admin, Role.school_admin])
def test_admins_have_no_billing_summary(sm: sessionmaker[Session], role: Role) -> None:
    admin = add_user(sm, role)
    assert _client(sm, admin, role).get(URL).status_code == 403


def test_an_assistant_gets_their_own_summary_never_the_leads(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher, display_name="Lead Teacher")
    helper = add_user(sm, Role.teacher, display_name="Helper")
    add_assistant(sm, teacher_id=lead, assistant_id=helper)
    _sub(sm, user=lead, tier=_tier(sm, audience=PlanAudience.teacher, included_seats=5), payer=lead)
    _card(sm, lead, "xxxx-xxxx-xxxx-9999")
    give(sm, lead, units=900)

    response = _client(sm, helper, Role.teacher).get(URL, headers={HEADER: str(lead)})

    assert response.status_code == 200
    body = response.json()
    assert body["beneficiary"]["userId"] == str(helper)
    assert body["subscription"] is None
    assert body["savedCard"] is None
    assert body["credits"]["totalUnits"] == 0


# --- teachers ----------------------------------------------------------------------------------


def test_teacher_summary_has_seats(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    tier = _tier(sm, audience=PlanAudience.teacher, included_seats=5, extra_seat_price_minor=2_500)
    _sub(sm, user=teacher, tier=tier, payer=teacher, extra_seats=1)
    for _ in range(2):
        add_seat(sm, teacher_id=teacher, student_id=add_user(sm, Role.student))

    body = _client(sm, teacher, Role.teacher).get(URL).json()

    assert body["beneficiary"]["audience"] == "teacher"
    assert body["seats"] == {"capacity": 6, "used": 2}
    assert body["subscription"]["extraSeats"] == 1


def test_a_teacher_without_a_plan_has_zero_capacity(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_seat(sm, teacher_id=teacher, student_id=add_user(sm, Role.student))
    body = _client(sm, teacher, Role.teacher).get(URL).json()
    assert body["subscription"] is None
    assert body["seats"] == {"capacity": 0, "used": 1}


def test_a_paid_plan_wins_over_a_manual_one(sm: sessionmaker[Session]) -> None:
    """R25: the manual row is older and inserted first, yet the paid row is the one shown."""
    teacher = add_user(sm, Role.teacher)
    manual_tier = _tier(sm, audience=PlanAudience.teacher, included_seats=1)
    paid_tier = _tier(sm, audience=PlanAudience.teacher, included_seats=8)
    _sub(sm, user=teacher, tier=manual_tier, payer=None, created_at=NOW - timedelta(days=30))
    paid = _sub(sm, user=teacher, tier=paid_tier, payer=teacher, created_at=NOW - timedelta(days=2))

    body = _client(sm, teacher, Role.teacher).get(URL).json()

    assert body["subscription"]["subscriptionId"] == str(paid)
    assert body["subscription"]["tier"]["planTierId"] == str(paid_tier)
    assert body["canManage"] is True
    assert body["seats"]["capacity"] == 8


# -- billed terms, a pending move and a platform cancel (UD13-A, P07-T16 review I-4 and M-5) ---


def _fixed_amount_client(sm: sessionmaker[Session], user: uuid.UUID, role: Role) -> TestClient:
    """The fixed-amount path: Paymob cannot change a subscription's amount (S14 failed)."""
    client = _client(sm, user, role)
    settings = Settings().model_copy(
        update={"paymob": PaymobSettings(subscription_amount_updatable=False)}
    )
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    return client


def _set_pending_terms(
    sm: sessionmaker[Session],
    sub: uuid.UUID,
    *,
    version: int,
    effective_at: datetime,
    notice_sent: bool = True,
    cancel: bool = False,
    cancel_source: str | None = None,
) -> None:
    with sm.begin() as session:
        row = session.get(Subscription, sub)
        assert row is not None
        row.pending_terms_version = version
        row.pending_terms_effective_at = effective_at
        row.terms_notice_sent_at = NOW - timedelta(days=1) if notice_sent else None
        row.cancel_at_period_end = cancel
        row.cancel_source = cancel_source


def _view(client: TestClient) -> dict[str, object]:
    body = client.get(URL).json()
    view = body["subscription"]
    assert isinstance(view, dict)
    return view


def test_the_summary_shows_the_billed_terms_not_the_live_tiers(sm: sessionmaker[Session]) -> None:
    """I-4: after an admin edit, before any notice or move, the payer still sees what they pay."""
    student = add_user(sm, Role.student)
    tier = _tier(sm, price_minor=9_900, included_seats=2, extra_seat_price_minor=300)
    _sub(sm, user=student, tier=tier, payer=student)
    edit_tier_terms(sm, tier, price_minor=14_000, included_seats=5, extra_seat_price_minor=700)
    shown = _view(_client(sm, student, Role.student))["tier"]
    assert isinstance(shown, dict)
    assert (shown["priceMinor"], shown["includedSeats"], shown["extraSeatPriceMinor"]) == (
        9_900,
        2,
        300,
    )
    assert "allowanceUnits" not in shown  # unit counts are never shown (spec 2.1)
    assert _view(_client(sm, student, Role.student))["pendingTermsChange"] is None


def test_the_catalogue_still_shows_the_tiers_current_terms(sm: sessionmaker[Session]) -> None:
    ensure_billing_settings(sm)  # the catalogue reads the credit validity
    student = add_user(sm, Role.student)
    tier = _tier(sm, price_minor=9_900)
    edit_tier_terms(sm, tier, price_minor=14_000)
    body = _client(sm, student, Role.student).get("/api/billing/catalogue").json()
    prices = {t["planTierId"]: t["priceMinor"] for t in body["planTiers"]}
    assert prices[str(tier)] == 14_000


def test_a_pending_move_is_shown_with_its_dates_and_what_changes(
    sm: sessionmaker[Session],
) -> None:
    teacher = add_user(sm, Role.teacher)
    tier = _tier(
        sm,
        audience=PlanAudience.teacher,
        price_minor=9_900,
        included_seats=5,
        extra_seat_price_minor=300,
    )
    sub = _sub(sm, user=teacher, tier=tier, payer=teacher)
    edit_tier_terms(sm, tier, price_minor=12_000, included_seats=3, allowance_units=400)
    effective = NOW + timedelta(days=13)
    _set_pending_terms(sm, sub, version=2, effective_at=effective)
    change = _view(_client(sm, teacher, Role.teacher))["pendingTermsChange"]
    assert isinstance(change, dict)
    assert datetime.fromisoformat(str(change["effectiveAt"])) == effective
    assert datetime.fromisoformat(str(change["firstRenewalAt"])) == NOW + timedelta(days=25)
    assert (change["priceMinor"], change["includedSeats"]) == (12_000, 3)
    assert change["priceChanges"] is True
    assert change["allowanceChange"] == "less"  # a direction, never the unit count
    assert (change["includedSeatsChanges"], change["seatAllowanceChanges"]) == (True, False)
    assert change["endsInsteadOfMoving"] is False
    assert "allowanceUnits" not in change


def test_a_move_that_changes_the_amount_ends_the_plan_on_the_fixed_path(
    sm: sessionmaker[Session],
) -> None:
    student = add_user(sm, Role.student)
    tier = _tier(sm, price_minor=9_900)
    sub = _sub(sm, user=student, tier=tier, payer=student)
    edit_tier_terms(sm, tier, price_minor=12_000)
    _set_pending_terms(sm, sub, version=2, effective_at=NOW + timedelta(days=13))
    change = _view(_fixed_amount_client(sm, student, Role.student))["pendingTermsChange"]
    assert isinstance(change, dict)
    assert change["endsInsteadOfMoving"] is True
    other = _view(_client(sm, student, Role.student))["pendingTermsChange"]
    assert isinstance(other, dict)
    assert other["endsInsteadOfMoving"] is False  # the updatable path moves the amount


def test_an_allowance_only_move_does_not_end_the_plan_on_the_fixed_path(
    sm: sessionmaker[Session],
) -> None:
    student = add_user(sm, Role.student)
    tier = _tier(sm, price_minor=9_900)
    sub = _sub(sm, user=student, tier=tier, payer=student)
    edit_tier_terms(sm, tier, allowance_units=2_000)
    _set_pending_terms(sm, sub, version=2, effective_at=NOW)
    change = _view(_fixed_amount_client(sm, student, Role.student))["pendingTermsChange"]
    assert isinstance(change, dict)
    assert (change["endsInsteadOfMoving"], change["allowanceChange"]) == (False, "more")


def test_a_platform_cancel_for_a_terms_move_carries_its_reason(sm: sessionmaker[Session]) -> None:
    """M-5: the payer sees why the plan is ending, not a bare "cancelling"."""
    student = add_user(sm, Role.student)
    tier = _tier(sm, price_minor=9_900)
    sub = _sub(sm, user=student, tier=tier, payer=student)
    edit_tier_terms(sm, tier, price_minor=12_000)
    _set_pending_terms(
        sm, sub, version=2, effective_at=NOW, cancel=True, cancel_source="platform_terms"
    )
    view = _view(_fixed_amount_client(sm, student, Role.student))
    assert (view["cancelAtPeriodEnd"], view["cancelReason"]) == (True, "plan_terms_changed")


def test_a_payers_own_cancel_has_no_reason(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    tier = _tier(sm, price_minor=9_900)
    sub = _sub(sm, user=student, tier=tier, payer=student, cancel_at_period_end=True)
    view = _view(_client(sm, student, Role.student))
    assert (view["cancelAtPeriodEnd"], view["cancelReason"]) == (True, None)
    edit_tier_terms(sm, tier, price_minor=12_000)
    _set_pending_terms(sm, sub, version=2, effective_at=NOW, cancel=True, cancel_source="payer")
    again = _view(_client(sm, student, Role.student))
    assert again["cancelReason"] is None  # only the platform's own cancel carries the reason
