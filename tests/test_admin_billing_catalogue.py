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
from pydantic import SecretStr
from sqlalchemy import func, select

from lemely.db.admin_billing_repo import (
    AdminCatalogueService,
    ReasonRequiredError,
    paymob_drift,
)
from lemely.db.models.billing import CreditPack, PlanTier, PlanTierTerms
from lemely.db.models.enums import PlanInterval, Role
from lemely.db.models.usage import UsageEstimator, UsageRate
from lemely.db.usage_catalogue_repo import SIGNUP_STUDENT_PACK
from lemely.io.paymob.client import PaymobError, PaymobNotConfigured
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_credit_pack,
    add_plan_tier,
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
        "priceMinor": 25000,
        "allowanceUnits": 1000,
        "includedSeats": 0,
        "seatAllowanceUnits": 0,
        "extraSeatPriceMinor": 0,
        "features": {},
        "isActive": True,
        "reason": "price rise",
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
    assert (first.before["price_minor"], first.after["price_minor"]) == (20000, 25000)
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
        assert row.paymob_plan_mode == "test"

    changed = client.put(f"{P}/tiers/{tier}", json=_tier_update(priceMinor=25000))
    assert changed.status_code == 200, changed.text
    assert changed.json()["paymobDrift"] == "drifted"
    [sync_row] = audit_rows(sm, "catalogue.plan_tier.sync_paymob")
    assert sync_row.before is not None and sync_row.after is not None
    assert sync_row.before["paymob_plan_id"] is None
    assert sync_row.after["paymob_plan_id"] == 9001
    assert sync_row.after["paymob_plan_synced_price_minor"] == 20000


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
        }
        base.update(fields)
        return PlanTier(**base)

    assert paymob_drift(tier(paymob_plan_id=None, paymob_plan_mode=None), "test") == "not_synced"
    assert paymob_drift(tier(paymob_plan_synced_price_minor=None), "test") == "unverified"
    assert paymob_drift(tier(), "test") == "in_sync"
    assert paymob_drift(tier(price_minor=30000), "test") == "drifted"
    assert paymob_drift(tier(paymob_plan_synced_frequency=360), "test") == "drifted"
    assert paymob_drift(tier(), "live") == "drifted"


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
