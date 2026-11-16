"""Admin catalogue (spec §8 area 1): every write is audited; versioned rows are never mutated.

A refused write (409/422/502) leaves no change and no audit row. Money guards here are
proven red by mutation in the task report, not just asserted green.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy import event as sa_event
from sqlalchemy import func, select

from lemely.db.admin_billing_repo import (
    AdminCatalogueService,
    AdminConflictError,
    ReasonRequiredError,
    paymob_drift,
)
from lemely.db.models.billing import (
    AutoTopupSettings,
    CreditPack,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanTier,
    PlanTierTerms,
    Subscription,
)
from lemely.db.models.billing_ops import BillingSettings
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.usage import UsageEstimator, UsageRate
from lemely.db.usage_catalogue_repo import SIGNUP_STUDENT_PACK
from lemely.io.paymob.client import PaymobError, PaymobNotConfigured
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_credit_pack,
    add_plan_tier,
    add_subscription,
    add_user,
    admin_client,
    audit_count,
    audit_rows,
    billing_database,
    emptied_after,
)
from tests.paymob_fixtures import PAYMOB_SETTINGS

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

P = "/api/admin/billing"


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


TEACHER_TIER: dict[str, Any] = {
    "code": "teacher_monthly",
    "name": "Teacher monthly",
    "audience": "teacher",
    "interval": "monthly",
    "priceMinor": 50000,
    "allowanceUnits": 5000,
    "includedSeats": 10,
    "seatAllowanceUnits": 300,
    "extraSeatPriceMinor": 2500,
    "reason": "launch catalogue",
}


def _tier_update(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Student monthly",
        "priceMinor": 20000,
        "allowanceUnits": 1000,
        "includedSeats": 0,
        "seatAllowanceUnits": 0,
        "extraSeatPriceMinor": 0,
        "features": {},
        "isActive": True,
        "reason": "rename",
    }
    body.update(changes)
    return body


# -- tiers ------------------------------------------------------------------------


def test_create_tier_is_audited_unsynced_and_gets_terms_v1_from_the_database(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    resp = admin_client(sm, admin).post(f"{P}/tiers", json=TEACHER_TIER)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["includedSeats"] == 10
    assert body["paymobDrift"] == "not_synced"
    [row] = audit_rows(sm, "catalogue.plan_tier.create")
    assert row.admin_user_id == admin
    assert row.target_id == uuid.UUID(body["id"])
    assert row.reason == "launch catalogue"
    assert row.before is None
    assert row.after is not None
    assert row.after["price_minor"] == 50000
    # trg_plan_tiers_seed_terms wrote version 1; a second insert from the service would have
    # violated the unique key and refused the create.
    with sm() as session:
        terms = session.scalars(
            select(PlanTierTerms).where(PlanTierTerms.plan_tier_id == uuid.UUID(body["id"]))
        ).all()
    assert [(t.terms_version, t.price_minor, t.included_seats) for t in terms] == [(1, 50000, 10)]


def test_a_student_tier_with_seat_fields_is_refused(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    body = {**TEACHER_TIER, "code": "student_monthly", "audience": "student"}
    resp = admin_client(sm, admin).post(f"{P}/tiers", json=body)

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "seat_fields_on_student_tier"
    assert audit_count(sm) == 0
    with sm() as session:
        assert session.scalars(select(PlanTier)).all() == []


def test_a_duplicate_tier_code_is_409_and_adds_no_second_audit_row(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    assert client.post(f"{P}/tiers", json=TEACHER_TIER).status_code == 200
    second = client.post(f"{P}/tiers", json=TEACHER_TIER)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "code_taken"
    assert audit_count(sm) == 1


def test_a_blank_reason_is_422_and_writes_nothing(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    resp = admin_client(sm, admin).post(f"{P}/tiers", json={**TEACHER_TIER, "reason": "  "})
    assert resp.status_code == 422
    with sm() as session:
        assert session.scalars(select(PlanTier)).all() == []
    assert audit_count(sm) == 0


def test_the_service_refuses_a_blank_reason_before_it_touches_anything(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    service = AdminCatalogueService(sm, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: NOW)
    tier = add_plan_tier(sm)
    with pytest.raises(ReasonRequiredError):
        service.update_plan_tier(tier, {"price_minor": 1}, admin_user_id=admin, reason="  ")
    with pytest.raises(ReasonRequiredError):
        service.sync_paymob_plan(tier, admin_user_id=admin, reason="")
    with sm() as session:
        assert session.get(PlanTier, tier).price_minor == 20000  # type: ignore[union-attr]
    assert audit_count(sm) == 0


def test_update_replaces_features_whole_and_audits_before_and_after(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    client = admin_client(sm, admin)
    client.put(f"{P}/tiers/{tier}", json=_tier_update(features={"a": 1, "b": 2}))
    resp = client.put(f"{P}/tiers/{tier}", json=_tier_update(features={"b": 3}))

    assert resp.status_code == 200, resp.text
    assert resp.json()["features"] == {"b": 3}
    first, second = audit_rows(sm, "catalogue.plan_tier.update")
    assert first.before is not None and first.after is not None
    assert (first.before["name"], first.after["name"]) == ("Student Monthly", "Student monthly")
    assert second.after is not None and second.after["features"] == {"b": 3}


def test_updating_an_unknown_tier_is_404_and_audits_nothing(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    resp = admin_client(sm, admin).put(f"{P}/tiers/{uuid.uuid4()}", json=_tier_update())
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "plan_tier_not_found"
    assert audit_count(sm) == 0


def test_a_student_tier_update_with_seats_is_refused_and_leaves_the_tier(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    resp = admin_client(sm, admin).put(f"{P}/tiers/{tier}", json=_tier_update(includedSeats=3))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "seat_fields_on_student_tier"
    with sm() as session:
        assert session.get(PlanTier, tier).included_seats == 0  # type: ignore[union-attr]
    assert audit_count(sm) == 0


# -- plan sync (DV-9, DV-10, DV-11) -------------------------------------------------


def test_sync_stamps_price_and_frequency_and_shows_drift_after_a_price_change(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm, code="student_monthly", price_minor=20000)
    paymob = FakePaymobClient()
    client = admin_client(sm, admin, paymob=paymob)

    synced = client.post(f"{P}/tiers/{tier}/sync", json={"reason": "first sync"})

    assert synced.status_code == 200, synced.text
    assert synced.json()["paymobPlanId"] == 9001
    assert synced.json()["paymobDrift"] == "in_sync"
    [(name, call)] = paymob.calls
    assert name == "create_plan"
    assert call["amount_cents"] == 20000
    assert call["frequency_days"] == 30
    assert call["use_transaction_amount"] is True
    with sm() as session:
        row = session.get(PlanTier, tier)
        assert row is not None
        assert (row.paymob_plan_synced_price_minor, row.paymob_plan_synced_frequency) == (20000, 30)
        assert row.paymob_plan_synced_retrial_days == 3 == call["retrial_days"]
        assert row.paymob_plan_mode == "test"

    # A price edit through the API is refused until T13 (see the terms tests); move it directly.
    with sm.begin() as session:
        session.execute(sa.update(PlanTier).where(PlanTier.id == tier).values(price_minor=25000))
    drifted = client.get(f"{P}/catalogue").json()["planTiers"]
    assert [t["paymobDrift"] for t in drifted] == ["drifted"]
    [sync_row] = audit_rows(sm, "catalogue.plan_tier.sync_paymob")
    assert sync_row.before is not None and sync_row.after is not None
    assert sync_row.before["paymob_plan_id"] is None
    assert sync_row.after["paymob_plan_id"] == 9001
    assert sync_row.after["paymob_plan_synced_price_minor"] == 20000


def test_changing_grace_days_marks_synced_tiers_drifted_until_synced_again(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm, code="student_monthly", price_minor=20000)
    paymob = FakePaymobClient()
    client = admin_client(sm, admin, paymob=paymob)
    assert client.post(f"{P}/tiers/{tier}/sync", json={"reason": "first"}).status_code == 200

    try:
        with sm.begin() as session:
            session.execute(sa.update(BillingSettings).values(grace_days=4))
        [listed] = client.get(f"{P}/catalogue").json()["planTiers"]
        assert listed["paymobDrift"] == "drifted"

        resync = client.post(f"{P}/tiers/{tier}/sync", json={"reason": "grace days moved"})
        assert resync.status_code == 200, resync.text
        assert resync.json()["paymobDrift"] == "in_sync"
        assert [c["retrial_days"] for name, c in paymob.calls if name == "create_plan"] == [3, 4]
    finally:
        with sm.begin() as session:
            session.execute(sa.update(BillingSettings).values(grace_days=3))


def test_a_tier_linked_before_retrial_days_was_stamped_is_unverified(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    add_plan_tier(
        sm,
        paymob_plan_id=7001,
        paymob_plan_mode="test",
        synced_price_minor=20000,
        synced_frequency=30,
    )
    [listed] = admin_client(sm, admin).get(f"{P}/catalogue").json()["planTiers"]
    assert listed["paymobDrift"] == "unverified"


def test_a_yearly_tier_is_stamped_with_the_yearly_frequency(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(
        sm, code="student_yearly", interval=PlanInterval.yearly, price_minor=200000
    )
    resp = admin_client(sm, admin).post(f"{P}/tiers/{tier}/sync", json={"reason": "yearly sync"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["paymobDrift"] == "in_sync"
    with sm() as session:
        assert session.get(PlanTier, tier).paymob_plan_synced_frequency == 360  # type: ignore[union-attr]


def test_a_tier_linked_under_test_keys_is_drifted_when_the_keys_are_live(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(
        sm,
        paymob_plan_id=7001,
        paymob_plan_mode="test",
        synced_price_minor=20000,
        synced_frequency=30,
        synced_retrial_days=3,
    )
    test_keys = admin_client(sm, admin).get(f"{P}/catalogue").json()["planTiers"]
    assert [t["paymobDrift"] for t in test_keys] == ["in_sync"]

    live = PAYMOB_SETTINGS.model_copy(
        update={"secret_key": SecretStr("egy_sk_live_secret"), "public_key": "egy_pk_live_public"}
    )
    assert live.key_mode == "live"
    live_keys = admin_client(sm, admin, paymob_settings=live).get(f"{P}/catalogue").json()
    assert [(t["id"], t["paymobDrift"]) for t in live_keys["planTiers"]] == [(str(tier), "drifted")]


def test_paymob_drift_states() -> None:
    def tier(**fields: Any) -> PlanTier:
        base: dict[str, Any] = {
            "price_minor": 20000,
            "interval": PlanInterval.monthly,
            "paymob_plan_id": 1,
            "paymob_plan_mode": "test",
            "paymob_plan_synced_price_minor": 20000,
            "paymob_plan_synced_frequency": 30,
            "paymob_plan_synced_retrial_days": 3,
        }
        base.update(fields)
        return PlanTier(**base)

    assert paymob_drift(tier(paymob_plan_id=None, paymob_plan_mode=None), "test", 3) == "not_synced"
    assert paymob_drift(tier(paymob_plan_synced_price_minor=None), "test", 3) == "unverified"
    assert paymob_drift(tier(), "test", 3) == "in_sync"
    assert paymob_drift(tier(price_minor=30000), "test", 3) == "drifted"
    assert paymob_drift(tier(paymob_plan_synced_frequency=360), "test", 3) == "drifted"
    assert paymob_drift(tier(), "live", 3) == "drifted"


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (PaymobError("boom", status_code=503), 502, "paymob_plan_create_failed"),
        (PaymobError("no answer"), 502, "paymob_plan_create_failed"),
        (PaymobNotConfigured("no secret key"), 502, "paymob_not_configured"),
        ({}, 502, "paymob_plan_response_unusable"),
        ({"id": "not-an-int"}, 502, "paymob_plan_response_unusable"),
    ],
    ids=["5xx", "no_answer", "not_configured", "no_plan_id", "bad_plan_id"],
)
def test_a_failed_sync_is_502_and_leaves_the_tier_unlinked_and_unaudited(
    sm: sessionmaker[Session],
    admin: uuid.UUID,
    failure: BaseException | dict[str, Any],
    status: int,
    code: str,
) -> None:
    tier = add_plan_tier(sm)
    paymob = FakePaymobClient()
    paymob.create_plan_result = failure
    resp = admin_client(sm, admin, paymob=paymob).post(
        f"{P}/tiers/{tier}/sync", json={"reason": "sync"}
    )

    assert resp.status_code == status, resp.text
    assert resp.json()["detail"]["code"] == code
    with sm() as session:
        row = session.get(PlanTier, tier)
        assert row is not None
        assert (row.paymob_plan_id, row.paymob_plan_mode) == (None, None)
        assert row.paymob_plan_synced_price_minor is None
    assert audit_count(sm) == 0


def test_an_unexpected_error_is_not_swallowed_into_a_502(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    paymob = FakePaymobClient()
    paymob.create_plan_result = RuntimeError("bug in our code")
    client = admin_client(sm, admin, paymob=paymob)
    with pytest.raises(RuntimeError, match="bug in our code"):
        client.post(f"{P}/tiers/{tier}/sync", json={"reason": "sync"})
    with sm() as session:
        assert session.get(PlanTier, tier).paymob_plan_id is None  # type: ignore[union-attr]
    assert audit_count(sm) == 0


def test_a_free_tier_cannot_be_synced(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    tier = add_plan_tier(sm, price_minor=0)
    paymob = FakePaymobClient()
    resp = admin_client(sm, admin, paymob=paymob).post(
        f"{P}/tiers/{tier}/sync", json={"reason": "sync"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "not_billable"
    assert paymob.calls == []
    assert audit_count(sm) == 0


def test_syncing_an_unknown_tier_is_404(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).post(f"{P}/tiers/{uuid.uuid4()}/sync", json={"reason": "sync"})
    assert resp.status_code == 404
    assert audit_count(sm) == 0


# -- packs and free allowances (DV-29) ----------------------------------------------


def test_credit_pack_create_and_update_are_audited(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    created = client.post(
        f"{P}/packs",
        json={
            "code": "pack_500",
            "name": "500 credits",
            "units": 500,
            "priceMinor": 10000,
            "reason": "launch",
        },
    )
    assert created.status_code == 200, created.text
    pack_id = created.json()["id"]
    updated = client.put(
        f"{P}/packs/{pack_id}",
        json={
            "name": "500 credits",
            "units": 550,
            "priceMinor": 10000,
            "isActive": False,
            "reason": "promo",
        },
    )
    assert updated.status_code == 200
    assert (updated.json()["units"], updated.json()["isActive"]) == (550, False)
    assert len(audit_rows(sm, "catalogue.credit_pack.create")) == 1
    [row] = audit_rows(sm, "catalogue.credit_pack.update")
    assert row.before is not None and row.after is not None
    assert (row.before["units"], row.after["units"]) == (500, 550)


def test_a_duplicate_pack_code_is_409(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    add_credit_pack(sm, code="pack_500")
    resp = admin_client(sm, admin).post(
        f"{P}/packs",
        json={"code": "pack_500", "name": "x", "units": 5, "priceMinor": 5, "reason": "dup"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "code_taken"
    assert audit_count(sm) == 0


def test_a_pack_code_with_the_signup_prefix_cannot_be_created(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    resp = admin_client(sm, admin).post(
        f"{P}/packs",
        json={
            "code": "signup_x",
            "name": "free",
            "units": 5,
            "priceMinor": 100,
            "reason": "sneaky sellable signup",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "reserved_code"
    with sm() as session:
        assert session.scalars(select(CreditPack)).all() == []
    assert audit_count(sm) == 0


def test_a_signup_pack_cannot_be_edited_as_a_sellable_pack(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    pack_id = client.put(
        f"{P}/free-allowances", json={"audience": "student", "units": 300, "reason": "seed"}
    ).json()["creditPackId"]
    audits_before = audit_count(sm)

    resp = client.put(
        f"{P}/packs/{pack_id}",
        json={
            "name": "free",
            "units": 300,
            "priceMinor": 1000,
            "isActive": True,
            "reason": "make it sellable",
        },
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "signup_pack_use_free_allowances"
    with sm() as session:
        pack = session.scalars(
            select(CreditPack).where(CreditPack.code == SIGNUP_STUDENT_PACK)
        ).one()
        assert (pack.units, pack.price_minor, pack.is_active) == (300, 0, False)
    assert audit_count(sm) == audits_before


def test_free_allowances_edit_the_signup_packs_units_only(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    student = client.put(
        f"{P}/free-allowances",
        json={"audience": "student", "units": 300, "reason": "three papers, not two"},
    )
    teacher = client.put(
        f"{P}/free-allowances",
        json={"audience": "teacher", "units": 2500, "reason": "launch promo"},
    )
    assert student.status_code == 200, student.text
    assert (student.json()["units"], student.json()["validDays"]) == (300, None)
    assert (teacher.json()["units"], teacher.json()["validDays"]) == (2500, 30)
    with sm() as session:
        pack = session.scalars(
            select(CreditPack).where(CreditPack.code == SIGNUP_STUDENT_PACK)
        ).one()
        assert (pack.units, pack.price_minor, pack.is_active) == (300, 0, False)
    rows = audit_rows(sm, "catalogue.free_allowance.update")
    assert rows[0].before is not None and rows[0].after is not None
    assert [r.after["units"] for r in rows if r.after] == [300, 2500]
    assert rows[0].before["units"] == 250  # Phase 04's default for students
    body = client.get(f"{P}/catalogue").json()
    assert sorted(f["audience"] for f in body["freeAllowances"]) == ["student", "teacher"]
    assert body["creditPacks"] == []  # signup packs are never listed as sellable packs


def test_a_free_allowance_of_zero_is_saved_and_shown_and_stays_inactive_at_price_zero(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    resp = client.put(
        f"{P}/free-allowances", json={"audience": "student", "units": 0, "reason": "paused promo"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["units"] == 0
    shown = client.get(f"{P}/catalogue").json()["freeAllowances"]
    assert [(f["audience"], f["units"]) for f in shown if f["audience"] == "student"] == [
        ("student", 0)
    ]
    with sm() as session:
        pack = session.scalars(
            select(CreditPack).where(CreditPack.code == SIGNUP_STUDENT_PACK)
        ).one()
        assert (pack.units, pack.price_minor, pack.is_active) == (0, 0, False)


def test_a_negative_free_allowance_is_refused(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).put(
        f"{P}/free-allowances", json={"audience": "student", "units": -1, "reason": "oops"}
    )
    assert resp.status_code == 422
    assert audit_count(sm) == 0


def test_every_signup_prefixed_pack_is_hidden_from_the_sellable_list(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    add_credit_pack(sm, code="signup_legacy")
    add_credit_pack(sm, code="pack_500")
    body = admin_client(sm, admin).get(f"{P}/catalogue").json()
    assert [p["code"] for p in body["creditPacks"]] == ["pack_500"]


# -- versioned rows -----------------------------------------------------------------


def test_a_backdated_version_is_refused(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).post(
        f"{P}/rates",
        json={
            "action": "mark_paper",
            "unitsPerUsd": 1000,
            "effectiveFrom": (NOW - timedelta(days=1)).isoformat(),
            "reason": "backdate",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "effective_from_in_past"
    assert audit_count(sm) == 0


def test_a_start_within_the_five_minute_tolerance_is_accepted(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    resp = admin_client(sm, admin).post(
        f"{P}/rates",
        json={
            "action": "mark_paper",
            "unitsPerUsd": 1000,
            "effectiveFrom": (NOW - timedelta(minutes=4)).isoformat(),
            "reason": "clock skew",
        },
    )
    assert resp.status_code == 200, resp.text


def test_a_naive_effective_from_is_422_on_rates_and_estimators(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    naive = (NOW + timedelta(days=1)).replace(tzinfo=None).isoformat()
    rate = client.post(
        f"{P}/rates",
        json={
            "action": "mark_paper",
            "unitsPerUsd": 1000,
            "effectiveFrom": naive,
            "reason": "naive",
        },
    )
    estimator = client.post(
        f"{P}/estimators",
        json={
            "action": "mark_paper",
            "inputKind": "pages",
            "baseLow": 1,
            "baseHigh": 2,
            "perInputLow": 1,
            "perInputHigh": 2,
            "effectiveFrom": naive,
            "reason": "naive",
        },
    )
    for resp in (rate, estimator):
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "naive_datetime"
    assert audit_count(sm) == 0


def test_usage_rates_version_per_action_and_never_mutate(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    for action, rate in (("mark_paper", 1000), ("regrade", 800), ("mark_paper", 1200)):
        resp = client.post(
            f"{P}/rates", json={"action": action, "unitsPerUsd": rate, "reason": "tune"}
        )
        assert resp.status_code == 200, resp.text
    with sm() as session:
        rows = session.scalars(
            select(UsageRate).order_by(UsageRate.action, UsageRate.version)
        ).all()
    assert [(r.action, r.version, r.units_per_usd) for r in rows] == [
        ("mark_paper", 1, 1000),
        ("mark_paper", 2, 1200),
        ("regrade", 1, 800),
    ]
    rows_audit = audit_rows(sm, "catalogue.usage_rate.version")
    assert len(rows_audit) == 3
    second_mark = rows_audit[2]
    assert second_mark.before is not None and second_mark.after is not None
    assert (second_mark.before["units_per_usd"], second_mark.after["units_per_usd"]) == (1000, 1200)


def test_concurrent_rate_versions_for_one_action_never_collide(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    workers = 6
    barrier = threading.Barrier(workers)

    def post(index: int) -> int:
        service = AdminCatalogueService(sm, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: NOW)
        barrier.wait()
        return service.add_usage_rate(
            action="mark_paper",
            units_per_usd=1000 + index,
            effective_from=None,
            admin_user_id=admin,
            reason="race",
        ).version

    with ThreadPoolExecutor(max_workers=workers) as pool:
        versions = sorted(pool.map(post, range(workers)))

    assert versions == [1, 2, 3, 4, 5, 6]
    assert len(audit_rows(sm, "catalogue.usage_rate.version")) == workers


def test_concurrent_estimator_versions_for_one_action_never_collide(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    from lemely.db.models.usage import EstimatorInputKind

    workers = 4
    barrier = threading.Barrier(workers)

    def post(index: int) -> int:
        service = AdminCatalogueService(sm, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: NOW)
        barrier.wait()
        return service.add_usage_estimator(
            action="mark_paper",
            input_kind=EstimatorInputKind.pages,
            base_low=1,
            base_high=2 + index,
            per_input_low=1,
            per_input_high=2,
            effective_from=None,
            admin_user_id=admin,
            reason="race",
        ).version

    with ThreadPoolExecutor(max_workers=workers) as pool:
        assert sorted(pool.map(post, range(workers))) == [1, 2, 3, 4]


def test_an_unknown_action_is_refused(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).post(
        f"{P}/rates", json={"action": "mine_bitcoin", "unitsPerUsd": 1, "reason": "x y z"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "unknown_action"
    assert audit_count(sm) == 0


def _estimator(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "action": "mark_paper",
        "inputKind": "pages",
        "baseLow": 1,
        "baseHigh": 2,
        "perInputLow": 1,
        "perInputHigh": 2,
        "reason": "tune",
    }
    body.update(changes)
    return body


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"baseLow": 5, "baseHigh": 3}, "low_above_high"),
        ({"perInputLow": 5, "perInputHigh": 3}, "low_above_high"),
        (
            {"inputKind": "none", "perInputLow": 1, "perInputHigh": 2},
            "per_input_without_input_kind",
        ),
        ({"action": "mine_bitcoin"}, "unknown_action"),
    ],
    ids=["base", "per_input", "no_input_kind", "unknown_action"],
)
def test_a_refused_estimator_leaves_no_row_and_no_audit(
    sm: sessionmaker[Session], admin: uuid.UUID, changes: dict[str, Any], code: str
) -> None:
    resp = admin_client(sm, admin).post(f"{P}/estimators", json=_estimator(**changes))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == code
    with sm() as session:
        assert session.scalar(select(func.count()).select_from(UsageEstimator)) == 0
    assert audit_count(sm) == 0


def test_an_estimator_with_no_input_kind_and_no_per_input_is_accepted(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    resp = admin_client(sm, admin).post(
        f"{P}/estimators", json=_estimator(inputKind="none", perInputLow=0, perInputHigh=0)
    )
    assert resp.status_code == 200, resp.text
    [row] = audit_rows(sm, "catalogue.usage_estimator.version")
    assert row.before is None


def test_get_catalogue_lists_everything(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    add_plan_tier(sm)
    client = admin_client(sm, admin)
    client.post(f"{P}/estimators", json=_estimator(reason="seed"))
    body = client.get(f"{P}/catalogue").json()
    assert [t["code"] for t in body["planTiers"]] == ["student_monthly"]
    assert [(e["action"], e["version"]) for e in body["usageEstimators"]] == [("mark_paper", 1)]
    assert body["creditPacks"] == [] and body["freeAllowances"] == [] and body["usageRates"] == []


# -- one audit row per write, refused writes leave none ------------------------------


def test_each_catalogue_write_adds_exactly_one_audit_row(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    pack = add_credit_pack(sm)
    client = admin_client(sm, admin)
    writes = [
        client.post(f"{P}/tiers", json=TEACHER_TIER),
        client.put(f"{P}/tiers/{tier}", json=_tier_update()),
        client.post(f"{P}/tiers/{tier}/sync", json={"reason": "sync it"}),
        client.post(
            f"{P}/packs",
            json={"code": "pack_9", "name": "n", "units": 9, "priceMinor": 9, "reason": "new pack"},
        ),
        client.put(
            f"{P}/packs/{pack}",
            json={"name": "n", "units": 9, "priceMinor": 9, "isActive": True, "reason": "edit"},
        ),
        client.put(
            f"{P}/free-allowances", json={"audience": "teacher", "units": 5, "reason": "edit"}
        ),
        client.post(
            f"{P}/rates", json={"action": "mark_paper", "unitsPerUsd": 5, "reason": "tune"}
        ),
        client.post(f"{P}/estimators", json=_estimator()),
    ]
    assert [w.status_code for w in writes] == [200] * 8, [w.text for w in writes]
    assert audit_count(sm) == 8


# -- terms history: an edit inserts the next terms row (UD13-A) -----------------------


def _terms(sm: sessionmaker[Session], tier_id: str | uuid.UUID) -> list[PlanTierTerms]:
    with sm() as session:
        return list(
            session.scalars(
                select(PlanTierTerms)
                .where(PlanTierTerms.plan_tier_id == uuid.UUID(str(tier_id)))
                .order_by(PlanTierTerms.terms_version)
            )
        )


def _tier_body(created: dict[str, Any], **change: Any) -> dict[str, Any]:
    return {
        "name": created["name"],
        "priceMinor": created["priceMinor"],
        "allowanceUnits": created["allowanceUnits"],
        "includedSeats": created["includedSeats"],
        "seatAllowanceUnits": created["seatAllowanceUnits"],
        "extraSeatPriceMinor": created["extraSeatPriceMinor"],
        "features": {},
        "isActive": True,
        "reason": "edit terms",
        **change,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"priceMinor": 30000},
        {"allowanceUnits": 1500},
        {"extraSeatPriceMinor": 100},
        {"includedSeats": 3},
        {"seatAllowanceUnits": 50},
    ],
    ids=["price", "allowance", "extra_seat_price", "included_seats", "seat_allowance"],
)
def test_a_terms_change_bumps_terms_version_and_the_history_equals_the_tier(
    sm: sessionmaker[Session], admin: uuid.UUID, change: dict[str, Any]
) -> None:
    client = admin_client(sm, admin)
    created = client.post(f"{P}/tiers", json=TEACHER_TIER).json()

    resp = client.put(f"{P}/tiers/{created['id']}", json=_tier_body(created, **change))

    assert resp.status_code == 200, resp.text
    assert resp.json()["termsVersion"] == 2
    history = _terms(sm, created["id"])
    assert [t.terms_version for t in history] == [1, 2]
    assert (history[0].price_minor, history[0].allowance_units) == (50000, 5000)
    assert history[0].created_by is None
    assert history[1].created_by == admin
    with sm() as session:
        tier = session.get(PlanTier, uuid.UUID(created["id"]))
        assert tier is not None
        latest = history[-1]
        assert (
            tier.price_minor,
            tier.extra_seat_price_minor,
            tier.allowance_units,
            tier.included_seats,
            tier.seat_allowance_units,
            tier.terms_version,
        ) == (
            latest.price_minor,
            latest.extra_seat_price_minor,
            latest.allowance_units,
            latest.included_seats,
            latest.seat_allowance_units,
            latest.terms_version,
        )
    [row] = audit_rows(sm, "catalogue.plan_tier.update")
    assert row.before is not None and row.after is not None
    assert (row.before["terms_version"], row.after["terms_version"]) == (1, 2)


def test_a_name_only_edit_adds_no_terms_row_and_a_refused_edit_adds_none(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    created = client.post(f"{P}/tiers", json=TEACHER_TIER).json()
    ok = client.put(f"{P}/tiers/{created['id']}", json=_tier_body(created, name="Renamed"))
    bad = client.put(
        f"{P}/tiers/{created['id']}",
        json=_tier_body(created, priceMinor=60000, expectedVersion=99),
    )
    assert (ok.status_code, bad.status_code) == (200, 409)
    assert [t.terms_version for t in _terms(sm, created["id"])] == [1]
    assert ok.json()["termsVersion"] == 1


def test_a_stale_tier_edit_is_refused_before_any_terms_row_is_written(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    created = client.post(f"{P}/tiers", json=TEACHER_TIER).json()
    bad = client.put(
        f"{P}/tiers/{created['id']}",
        json=_tier_body(created, priceMinor=60000, expectedVersion=7),
    )
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "stale_write"
    assert audit_rows(sm, "catalogue.plan_tier.update") == []
    assert len(_terms(sm, created["id"])) == 1


def test_the_terms_row_is_inserted_before_terms_version_moves(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """DV-T1a order, observed in the SQL: nothing else enforces it (``plan_tiers`` has no FK)."""
    tier = add_plan_tier(sm)
    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any, **_kwargs: Any) -> None:
        statements.append(statement)

    engine = sm.kw["bind"]
    sa_event.listen(engine, "before_cursor_execute", record)
    try:
        admin_client(sm, admin).put(f"{P}/tiers/{tier}", json=_tier_update(priceMinor=30000))
    finally:
        sa_event.remove(engine, "before_cursor_execute", record)

    insert = next(
        i for i, q in enumerate(statements) if q.startswith("INSERT INTO plan_tier_terms")
    )
    moves = [
        i
        for i, q in enumerate(statements)
        if q.startswith("UPDATE plan_tiers") and "terms_version" in q.split(" WHERE ")[0]
    ]
    assert moves, statements
    assert insert < min(moves)


def test_catalogue_counts_live_subscribers_and_those_behind_the_current_terms(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    client = admin_client(sm, admin)
    assert client.put(f"{P}/tiers/{tier}", json=_tier_update(priceMinor=30000)).status_code == 200
    add_subscription(sm, add_user(sm), tier)  # stamped terms v1; the tier is now at v2
    row = client.get(f"{P}/catalogue").json()["planTiers"][0]
    assert (row["liveSubscriptionCount"], row["pendingMoves"], row["termsVersion"]) == (1, 1, 2)


# -- terms edits with live subscribers (UD13-A: they move at their renewal, after a notice) ---


@pytest.mark.parametrize("status", ["active", "past_due", "pending_first_payment"])
def test_a_terms_edit_with_a_live_subscriber_succeeds_and_leaves_them_on_their_terms(
    sm: sessionmaker[Session], admin: uuid.UUID, status: str
) -> None:
    """The edit appends terms v2; the subscriber stays on v1 until the notice job and a renewal."""
    tier = add_plan_tier(sm, price_minor=10000)
    sub = add_subscription(sm, add_user(sm), tier, status=SubscriptionStatus(status))
    resp = admin_client(sm, admin).put(f"{P}/tiers/{tier}", json=_tier_update(priceMinor=15000))
    assert resp.status_code == 200, resp.text
    assert resp.json()["termsVersion"] == 2
    with sm() as session:
        row = session.get(PlanTier, tier)
        assert row is not None
        assert (row.price_minor, row.terms_version) == (15000, 2)
        held = session.get(Subscription, sub)
        assert held is not None
        assert (held.terms_version, held.pending_terms_version) == (1, None)
    assert [t.terms_version for t in _terms(sm, tier)] == [1, 2]
    assert len(audit_rows(sm, "catalogue.plan_tier.update")) == 1


def test_a_name_edit_is_allowed_with_a_live_subscriber_and_a_terms_edit_without_one(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    with_sub = add_plan_tier(sm, code="with_sub", price_minor=10000)
    add_subscription(sm, add_user(sm), with_sub)
    renamed = client.put(
        f"{P}/tiers/{with_sub}", json=_tier_update(priceMinor=10000, name="Renamed")
    )
    assert renamed.status_code == 200, renamed.text

    free = add_plan_tier(sm, code="no_subs", price_minor=10000)
    add_subscription(sm, add_user(sm), free, status=SubscriptionStatus.expired, end=None)
    edited = client.put(f"{P}/tiers/{free}", json=_tier_update(priceMinor=15000))
    assert edited.status_code == 200, edited.text
    assert edited.json()["termsVersion"] == 2


def test_a_seat_price_edit_leaves_a_seat_checkout_in_flight_untouched(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """M1: the in-flight seat payment is billed on the terms it was priced at; the edit is a new
    terms version and the settle path (``_terms_moved``) credits it if the terms moved."""
    tier = add_plan_tier(
        sm, code="seat_tier", audience="teacher", included_seats=2, extra_seat_price_minor=2000
    )
    teacher = add_user(sm, Role.teacher)
    sid = add_subscription(sm, teacher, tier)
    payment_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Payment(
                id=payment_id,
                special_reference=str(payment_id),
                payer_user_id=teacher,
                beneficiary_user_id=teacher,
                purpose=PaymentPurpose.extra_seats,
                subscription_id=sid,
                seat_quantity=2,
                amount_minor=2000,
                currency="EGP",
                status=PaymentStatus.created,
            )
        )
    resp = admin_client(sm, admin).put(
        f"{P}/tiers/{tier}",
        json=_tier_update(includedSeats=2, extraSeatPriceMinor=0, seatAllowanceUnits=0),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["termsVersion"] == 2
    with sm() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        assert (payment.status, payment.amount_minor) == (PaymentStatus.created, 2000)


def test_a_pack_update_returns_the_real_auto_topup_count(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm)
    for enabled in (True, True, False):
        user = add_user(sm)
        with sm.begin() as session:
            session.add(
                AutoTopupSettings(
                    beneficiary_user_id=user,
                    payer_user_id=user,
                    enabled=enabled,
                    threshold_units=10,
                    credit_pack_id=pack,
                    monthly_cap_minor=1000,
                )
            )
    resp = admin_client(sm, admin).put(
        f"{P}/packs/{pack}",
        json={"name": "n", "units": 9, "priceMinor": 9, "isActive": True, "reason": "edit"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["autoTopupCount"] == 2


def test_features_are_bounded_in_total_size(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    tier = add_plan_tier(sm)
    huge = admin_client(sm, admin).put(
        f"{P}/tiers/{tier}", json=_tier_update(features={"k": "x" * 20_000})
    )
    small = admin_client(sm, admin).put(
        f"{P}/tiers/{tier}", json=_tier_update(features={"k": "x" * 1_000})
    )
    assert (huge.status_code, small.status_code) == (422, 200)


# -- seat price 0 while extra seats are held (P06-T4 n3) -------------------------------


def test_a_seat_price_of_zero_is_refused_while_subscribers_hold_extra_seats(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    created = client.post(f"{P}/tiers", json=TEACHER_TIER).json()
    teacher = add_user(sm, Role.teacher)
    sid = add_subscription(sm, teacher, uuid.UUID(created["id"]))
    with sm.begin() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        sub.extra_seats = 3

    resp = client.put(f"{P}/tiers/{created['id']}", json=_tier_body(created, extraSeatPriceMinor=0))

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "extra_seats_held"
    assert audit_rows(sm, "catalogue.plan_tier.update") == []
    with sm.begin() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        sub.extra_seats = 0
    # With the seats gone the edit is a terms edit on a tier with a live subscriber: allowed.
    again = client.put(
        f"{P}/tiers/{created['id']}", json=_tier_body(created, extraSeatPriceMinor=0)
    )
    assert again.status_code == 200, again.text


# -- optimistic concurrency (UD13-DV-1) --------------------------------------------------


def test_expected_version_on_a_tier_matches_stale_and_absent(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    created = client.post(f"{P}/tiers", json=TEACHER_TIER).json()
    tid = created["id"]
    assert created["version"] == 1
    stale = client.put(f"{P}/tiers/{tid}", json=_tier_body(created, name="A", expectedVersion=5))
    match = client.put(f"{P}/tiers/{tid}", json=_tier_body(created, name="B", expectedVersion=1))
    absent = client.put(f"{P}/tiers/{tid}", json=_tier_body(created, name="C"))
    assert (stale.status_code, match.status_code, absent.status_code) == (409, 200, 200)
    assert stale.json()["detail"]["code"] == "stale_write"
    assert (match.json()["version"], absent.json()["version"]) == (2, 3)
    assert len(audit_rows(sm, "catalogue.plan_tier.update")) == 2


def test_expected_version_on_a_pack_matches_stale_and_absent(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm)
    client = admin_client(sm, admin)

    def put(**extra: Any) -> Any:
        return client.put(
            f"{P}/packs/{pack}",
            json={"name": "n", "units": 9, "priceMinor": 9, "isActive": True, "reason": "edit"}
            | extra,
        )

    stale, match, absent = put(expectedVersion=4), put(expectedVersion=1), put()
    assert (stale.status_code, match.status_code, absent.status_code) == (409, 200, 200)
    assert (match.json()["version"], absent.json()["version"]) == (2, 3)
    assert len(audit_rows(sm, "catalogue.credit_pack.update")) == 2


def test_expected_version_on_free_allowances_matches_stale_and_absent(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)

    def put(**extra: Any) -> Any:
        return client.put(
            f"{P}/free-allowances",
            json={"audience": "teacher", "units": 100, "reason": "edit"} | extra,
        )

    first = put()
    version = first.json()["version"]
    stale = put(expectedVersion=version + 5)
    match = put(expectedVersion=version)
    absent = put()
    assert (first.status_code, stale.status_code, match.status_code, absent.status_code) == (
        200,
        409,
        200,
        200,
    )
    assert stale.json()["detail"]["code"] == "stale_write"
    assert (match.json()["version"], absent.json()["version"]) == (version + 1, version + 2)
    assert len(audit_rows(sm, "catalogue.free_allowance.update")) == 3


def test_two_concurrent_puts_with_the_same_expected_version_one_wins(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    barrier = threading.Barrier(2)

    def edit(name: str) -> int:
        client = admin_client(sm, admin)
        barrier.wait(timeout=10)
        return client.put(
            f"{P}/tiers/{tier}", json=_tier_update(name=name, expectedVersion=1)
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(
            f.result(timeout=60) for f in [pool.submit(edit, "A"), pool.submit(edit, "B")]
        )
    assert codes == [200, 409]
    assert len(audit_rows(sm, "catalogue.plan_tier.update")) == 1


# -- validDays and the counts --------------------------------------------------------------


def test_valid_days_round_trips_and_zero_is_422(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    teacher = client.put(
        f"{P}/free-allowances",
        json={"audience": "teacher", "units": 2000, "validDays": 45, "reason": "longer"},
    )
    student = client.put(
        f"{P}/free-allowances",
        json={"audience": "student", "units": 250, "validDays": None, "reason": "never"},
    )
    zero = client.put(
        f"{P}/free-allowances",
        json={"audience": "teacher", "units": 1, "validDays": 0, "reason": "bad"},
    )
    assert (teacher.json()["validDays"], student.json()["validDays"]) == (45, None)
    assert zero.status_code == 422
    shown = {
        f["audience"]: f["validDays"] for f in client.get(f"{P}/catalogue").json()["freeAllowances"]
    }
    assert shown == {"teacher": 45, "student": None}
    rows = audit_rows(sm, "catalogue.free_allowance.update")
    assert rows[0].before is not None and rows[0].after is not None
    assert (rows[0].before["signup_validity_days"], rows[0].after["signup_validity_days"]) == (
        30,
        45,
    )


def test_an_absent_valid_days_keeps_the_stored_value(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    resp = client.put(
        f"{P}/free-allowances", json={"audience": "teacher", "units": 7, "reason": "units only"}
    )
    assert resp.json()["validDays"] == 30  # seeded by ensure_usage_catalogue (DV-T1d)


def test_live_subscription_and_auto_topup_counts(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    for status in (
        SubscriptionStatus.active,
        SubscriptionStatus.past_due,
        SubscriptionStatus.pending_first_payment,
        SubscriptionStatus.expired,
    ):
        add_subscription(sm, add_user(sm), tier, status=status, end=None)
    pack = add_credit_pack(sm)
    for enabled in (True, True, False):
        user = add_user(sm)
        with sm.begin() as session:
            session.add(
                AutoTopupSettings(
                    beneficiary_user_id=user,
                    payer_user_id=user,
                    enabled=enabled,
                    threshold_units=10,
                    credit_pack_id=pack,
                    monthly_cap_minor=1000,
                )
            )
    body = admin_client(sm, admin).get(f"{P}/catalogue").json()
    assert body["planTiers"][0]["liveSubscriptionCount"] == 3
    assert body["creditPacks"][0]["autoTopupCount"] == 2
    assert body["priceChangeNoticeDays"] == 14
    assert body["subscriptionAmountUpdatable"] is True


def test_a_name_features_and_active_edit_still_works_with_the_terms_unchanged(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm, price_minor=20000, allowance_units=1000)
    resp = admin_client(sm, admin).put(
        f"{P}/tiers/{tier}", json=_tier_update(name="Renamed", features={"x": 1}, isActive=False)
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["name"], resp.json()["isActive"], resp.json()["priceMinor"]) == (
        "Renamed",
        False,
        20000,
    )
    assert len(audit_rows(sm, "catalogue.plan_tier.update")) == 1


# -- DTO bounds follow the column types (M1) ------------------------------------------


def test_a_tier_price_above_the_integer_column_is_422_not_a_500(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    too_big = client.post(f"{P}/tiers", json={**TEACHER_TIER, "priceMinor": 3_000_000_000})
    assert too_big.status_code == 422
    biggest = client.post(f"{P}/tiers", json={**TEACHER_TIER, "priceMinor": 2**31 - 1})
    assert biggest.status_code == 200, biggest.text
    tier = biggest.json()["id"]
    update = _tier_update(priceMinor=3_000_000_000)
    assert client.put(f"{P}/tiers/{tier}", json=update).status_code == 422
    assert audit_count(sm) == 1


# -- versions never start before the latest (M2) --------------------------------------


@pytest.mark.parametrize("kind", ["rates", "estimators"])
def test_a_version_cannot_start_before_the_latest_one(
    sm: sessionmaker[Session], admin: uuid.UUID, kind: str
) -> None:
    client = admin_client(sm, admin)

    def post(effective_from: str | None) -> Any:
        body: dict[str, Any] = (
            {"action": "mark_paper", "unitsPerUsd": 1000, "reason": "tune"}
            if kind == "rates"
            else _estimator()
        )
        if effective_from is not None:
            body["effectiveFrom"] = effective_from
        return client.post(f"{P}/{kind}", json=body)

    later = (NOW + timedelta(days=30)).isoformat()
    assert post(later).status_code == 200
    audits = audit_count(sm)

    refused = post(None)  # starts now, before the scheduled version
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "effective_from_before_latest"
    assert post((NOW + timedelta(days=10)).isoformat()).status_code == 422
    assert audit_count(sm) == audits
    assert post((NOW + timedelta(days=31)).isoformat()).status_code == 200


# -- a failure after Paymob created the plan is alerted (M3) ---------------------------


def test_a_failure_after_the_plan_is_created_logs_an_orphan_alert_and_no_link(
    sm: sessionmaker[Session], admin: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    import structlog.testing

    from lemely.db import admin_billing_repo

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("audit insert failed")

    monkeypatch.setattr(admin_billing_repo, "audited", boom)
    tier = add_plan_tier(sm)
    paymob = FakePaymobClient()
    service = AdminCatalogueService(sm, paymob, PAYMOB_SETTINGS, now=lambda: NOW)

    with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError):
        service.sync_paymob_plan(tier, admin_user_id=admin, reason="sync")

    orphans = [e for e in logs if e["event"] == "paymob_plan_orphaned"]
    assert len(orphans) == 1
    assert orphans[0]["alert"] is True
    assert orphans[0]["paymob_plan_id"] == 9001
    assert orphans[0]["plan_tier_id"] == str(tier)
    with sm() as session:
        assert session.get(PlanTier, tier).paymob_plan_id is None  # type: ignore[union-attr]


def test_a_refusal_before_paymob_is_called_logs_no_orphan(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    import structlog.testing

    tier = add_plan_tier(sm, price_minor=0)
    service = AdminCatalogueService(sm, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: NOW)
    with structlog.testing.capture_logs() as logs, pytest.raises(Exception, match="no price"):
        service.sync_paymob_plan(tier, admin_user_id=admin, reason="sync")
    assert [e for e in logs if e["event"] == "paymob_plan_orphaned"] == []


# -- syncing a tier that is already in sync does not call Paymob (M4) ------------------


def test_syncing_an_in_sync_tier_is_409_and_calls_paymob_once_in_total(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    paymob = FakePaymobClient()
    client = admin_client(sm, admin, paymob=paymob)
    assert client.post(f"{P}/tiers/{tier}/sync", json={"reason": "first"}).status_code == 200

    again = client.post(f"{P}/tiers/{tier}/sync", json={"reason": "again"})

    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "already_in_sync"
    assert [name for name, _ in paymob.calls] == ["create_plan"]
    assert len(audit_rows(sm, "catalogue.plan_tier.sync_paymob")) == 1


def test_a_double_click_creates_one_plan(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    tier = add_plan_tier(sm)
    paymob = FakePaymobClient()
    barrier = threading.Barrier(2)

    def click(_: int) -> str:
        service = AdminCatalogueService(sm, paymob, PAYMOB_SETTINGS, now=lambda: NOW)
        barrier.wait()
        try:
            service.sync_paymob_plan(tier, admin_user_id=admin, reason="double click")
        except AdminConflictError as exc:
            return exc.code
        return "synced"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(click, range(2)))

    assert outcomes == ["already_in_sync", "synced"]
    assert [name for name, _ in paymob.calls] == ["create_plan"]


def test_a_drifted_tier_can_be_synced_again(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    tier = add_plan_tier(
        sm,
        paymob_plan_id=7001,
        paymob_plan_mode="test",
        synced_price_minor=15000,
        synced_frequency=30,
        synced_retrial_days=3,
    )
    paymob = FakePaymobClient()
    resp = admin_client(sm, admin, paymob=paymob).post(
        f"{P}/tiers/{tier}/sync", json={"reason": "price moved"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["paymobDrift"] == "in_sync"
    assert len(paymob.calls) == 1


# -- the tier row is locked for an edit (M6) ----------------------------------------


def test_a_tier_edit_waits_for_a_concurrent_writer_and_audits_what_it_replaced(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    import time

    tier = add_plan_tier(sm)
    service = AdminCatalogueService(sm, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: NOW)
    holder = sm()
    holder.begin()
    holder.execute(sa.update(PlanTier).where(PlanTier.id == tier).values(name="First writer"))

    def edit() -> None:
        service.update_plan_tier(
            tier, {"name": "Second writer"}, admin_user_id=admin, reason="edit"
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(edit)
        time.sleep(0.7)  # the edit must be parked on the row lock, not already past its read
        holder.commit()
        holder.close()
        future.result(timeout=30)

    [row] = audit_rows(sm, "catalogue.plan_tier.update")
    assert row.before is not None and row.after is not None
    assert row.before["name"] == "First writer"
    assert row.after["name"] == "Second writer"


def test_a_terms_edit_audits_the_terms_version_and_how_many_subscribers_it_moves(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm, price_minor=10000)
    add_subscription(sm, add_user(sm), tier)  # renewing, paid: the one that moves
    cancelling = add_subscription(sm, add_user(sm), tier)
    add_subscription(sm, add_user(sm), tier, manual=True)  # a manual activation does not renew
    with sm.begin() as session:
        row = session.get(Subscription, cancelling)
        assert row is not None
        row.cancel_at_period_end = True  # a cancelling subscriber is leaving: not moved
    resp = admin_client(sm, admin).put(f"{P}/tiers/{tier}", json=_tier_update(priceMinor=15000))
    assert resp.status_code == 200, resp.text
    [row] = audit_rows(sm, "catalogue.plan_tier.update")
    assert row.after is not None
    assert (row.after["termsVersion"], row.after["subscribersToMove"]) == (2, 1)


def test_a_name_only_edit_audits_no_subscribers_to_move(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm, price_minor=10000)
    add_subscription(sm, add_user(sm), tier)
    resp = admin_client(sm, admin).put(
        f"{P}/tiers/{tier}", json=_tier_update(priceMinor=10000, name="Renamed")
    )
    assert resp.status_code == 200, resp.text
    [row] = audit_rows(sm, "catalogue.plan_tier.update")
    assert row.after is not None
    assert (row.after["termsVersion"], row.after["subscribersToMove"]) == (1, 0)


def test_the_audit_count_leaves_out_a_subscriber_with_a_pending_plan_change(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """R3-M4: the notice job never moves a row whose pending plan change decides its terms."""
    tier = add_plan_tier(sm, price_minor=10000)
    other = add_plan_tier(sm, code="other_tier", price_minor=5000)
    add_subscription(sm, add_user(sm), tier)
    changing = add_subscription(sm, add_user(sm), tier)
    with sm.begin() as session:
        row = session.get(Subscription, changing)
        assert row is not None
        row.pending_plan_tier_id = other
    resp = admin_client(sm, admin).put(f"{P}/tiers/{tier}", json=_tier_update(priceMinor=15000))
    assert resp.status_code == 200, resp.text
    [row] = audit_rows(sm, "catalogue.plan_tier.update")
    assert row.after is not None
    assert row.after["subscribersToMove"] == 1
