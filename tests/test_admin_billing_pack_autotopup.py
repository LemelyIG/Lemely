"""A credit pack price change keeps auto top-ups charging the new price (P07 T17, UD13-B (a)).

Phase 06 reads ``pack.price_minor`` and ``pack.units`` when it queues a top-up and holds it to the
customer's monthly cap. This file pins that against a real pack edit through the admin API, and
checks that the admin sees how many settings now have a cap below the price (one grouped query
for the DTO, two counts in the audit ``after``).

Runs on a throwaway Postgres database (``create_all``); skips without a local Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.auto_topup_repo import _refuse_queued_payments, enqueue_auto_topup
from lemely.db.models.billing import (
    AutoTopupSettings,
    Payment,
    PaymentPurpose,
    PaymentStatus,
)
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger
from tests.admin_billing_db import (
    add_credit_pack,
    add_user,
    admin_client,
    audit_rows,
    billing_database,
    emptied_after,
)
from tests.merchant_charge_fixtures import seed_auto_topup, seed_saved_card

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

P = "/api/admin/billing"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


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


def _customer(
    sm: sessionmaker[Session], pack: uuid.UUID, *, cap: int = 50_000, enabled: bool = True
) -> uuid.UUID:
    """A self-paying student with 100 credits, an auto top-up at 500 and a saved card."""
    user = add_user(sm, Role.student)
    seed_auto_topup(
        sm,
        beneficiary_id=user,
        payer_id=user,
        pack_id=pack,
        card_id=seed_saved_card(sm, user),
        enabled=enabled,
        threshold=500,
        cap=cap,
        consented_at=NOW - timedelta(days=30),
    )
    with sm.begin() as session:
        UsageLedger(session).issue_grant(
            owner_user_id=user,
            kind=GrantKind.credit_pack,
            units=100,
            idempotency_key=f"seed:{user}",
            effective_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=90),
            visible=True,
        )
    return user


def _edit_pack(
    sm: sessionmaker[Session],
    admin: uuid.UUID,
    pack: uuid.UUID,
    *,
    units: int = 500,
    price_minor: int,
    is_active: bool = True,
) -> dict[str, object]:
    resp = admin_client(sm, admin).put(
        f"{P}/packs/{pack}",
        json={
            "name": "pack",
            "units": units,
            "priceMinor": price_minor,
            "isActive": is_active,
            "reason": "price change",
        },
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


def _enqueue(sm: sessionmaker[Session], owner: uuid.UUID) -> uuid.UUID | None:
    with sm.begin() as session:
        payment = enqueue_auto_topup(session, owner, now=NOW)
        return payment.id if payment is not None else None


def _setting(sm: sessionmaker[Session], owner: uuid.UUID) -> AutoTopupSettings:
    with sm() as session:
        return session.scalars(
            sa.select(AutoTopupSettings).where(AutoTopupSettings.beneficiary_user_id == owner)
        ).one()


def _payment(sm: sessionmaker[Session], payment_id: uuid.UUID) -> Payment:
    with sm() as session:
        return session.get_one(Payment, payment_id)


def test_a_raised_price_is_charged_at_the_new_price_with_the_new_units(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm, units=500, price_minor=10_000)
    user = _customer(sm, pack)
    _edit_pack(sm, admin, pack, units=600, price_minor=20_000)
    payment_id = _enqueue(sm, user)
    assert payment_id is not None
    payment = _payment(sm, payment_id)
    assert (payment.amount_minor, payment.grant_units) == (20_000, 600)
    assert payment.purpose is PaymentPurpose.auto_topup
    setting = _setting(sm, user)
    assert setting.enabled is True
    assert setting.last_payment_id == payment_id


def test_a_cap_below_the_new_price_enqueues_nothing_and_stays_enabled_and_armed(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm, price_minor=10_000)
    user = _customer(sm, pack, cap=15_000)
    body = _edit_pack(sm, admin, pack, price_minor=20_000)
    assert _enqueue(sm, user) is None
    setting = _setting(sm, user)
    assert (setting.enabled, setting.armed) == (True, True)
    assert body["autoTopupCount"] == 1
    assert body["autoTopupCapBelowPriceCount"] == 1
    catalogue = admin_client(sm, admin).get(f"{P}/catalogue").json()
    assert catalogue["creditPacks"][0]["autoTopupCapBelowPriceCount"] == 1
    [row] = audit_rows(sm, "catalogue.credit_pack.update")
    assert row.after is not None
    assert row.after["impact"] == {"autoTopupsAffected": 1, "autoTopupsCapBelowPrice": 1}
    assert row.before is not None
    assert row.before["impact"] == {"autoTopupsAffected": 1, "autoTopupsCapBelowPrice": 0}


def test_the_counts_cover_only_enabled_settings_on_this_pack_with_a_cap_below_the_price(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm, code="pack_a", price_minor=10_000)
    other = add_credit_pack(sm, code="pack_b", price_minor=10_000)
    _customer(sm, pack, cap=19_999)  # below the new price: counted
    _customer(sm, pack, cap=20_000)  # equal to the price: the cap still allows one charge
    _customer(sm, pack, cap=100, enabled=False)  # disabled: not counted at all
    _customer(sm, other, cap=100)  # another pack: not counted
    body = _edit_pack(sm, admin, pack, price_minor=20_000)
    assert (body["autoTopupCount"], body["autoTopupCapBelowPriceCount"]) == (2, 1)
    [row] = audit_rows(sm, "catalogue.credit_pack.update")
    assert row.after is not None
    assert row.after["impact"] == {"autoTopupsAffected": 2, "autoTopupsCapBelowPrice": 1}


def test_a_queued_payment_is_refused_at_charge_time_and_the_next_queue_uses_the_new_price(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """P06-T8: a changed pack fails a queued, unsent top-up as ``settings_changed`` and re-arms."""
    pack = add_credit_pack(sm, units=500, price_minor=10_000)
    user = _customer(sm, pack)
    queued = _enqueue(sm, user)
    assert queued is not None
    assert _payment(sm, queued).amount_minor == 10_000
    _edit_pack(sm, admin, pack, units=600, price_minor=20_000)
    assert _refuse_queued_payments(sm, now=NOW) == 1
    refused = _payment(sm, queued)
    assert refused.status is PaymentStatus.failed
    assert refused.last_callback == {"source": "pre_send", "reason": "settings_changed"}
    setting = _setting(sm, user)
    assert (setting.enabled, setting.armed) == (True, True)
    again = _enqueue(sm, user)
    assert again is not None and again != queued
    payment = _payment(sm, again)
    assert (payment.amount_minor, payment.grant_units) == (20_000, 600)


def test_a_queued_payment_refused_after_a_raise_past_the_cap_queues_nothing_more(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm, units=500, price_minor=10_000)
    user = _customer(sm, pack, cap=15_000)
    queued = _enqueue(sm, user)
    assert queued is not None
    _edit_pack(sm, admin, pack, units=500, price_minor=20_000)
    assert _refuse_queued_payments(sm, now=NOW) == 1
    assert _payment(sm, queued).last_callback == {
        "source": "pre_send",
        "reason": "settings_changed",
    }
    assert _enqueue(sm, user) is None
    setting = _setting(sm, user)
    assert (setting.enabled, setting.armed) == (True, True)


def test_the_price_impact_preview_counts_at_the_proposed_price_before_any_save(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm, price_minor=10_000)
    _customer(sm, pack, cap=15_000)
    _customer(sm, pack, cap=30_000)
    client = admin_client(sm, admin)

    def at(price: int) -> dict[str, int]:
        resp = client.get(f"{P}/packs/{pack}/price-impact", params={"priceMinor": price})
        body: dict[str, int] = resp.json()
        return body

    assert at(10_000) == {"autoTopupCount": 2, "capBelowPriceCount": 0}
    assert at(20_000) == {"autoTopupCount": 2, "capBelowPriceCount": 1}
    assert at(40_000) == {"autoTopupCount": 2, "capBelowPriceCount": 2}
    assert audit_rows(sm, "catalogue.credit_pack.update") == []
    assert client.get(f"{P}/catalogue").json()["creditPacks"][0]["autoTopupCapBelowPriceCount"] == 0


def test_the_price_impact_preview_is_bounded_and_404s_an_unknown_pack(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm)
    client = admin_client(sm, admin)
    for bad in (0, -1, 10**10 + 1):
        resp = client.get(f"{P}/packs/{pack}/price-impact", params={"priceMinor": bad})
        assert resp.status_code == 422
    assert client.get(f"{P}/packs/{pack}/price-impact").status_code == 422
    missing = client.get(f"{P}/packs/{uuid.uuid4()}/price-impact", params={"priceMinor": 5})
    assert missing.status_code == 404


def test_only_settings_that_can_fire_are_counted(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm, price_minor=10_000)
    _customer(sm, pack, cap=100)  # can fire, cap below: counted in both
    no_consent = add_user(sm, Role.student)
    seed_auto_topup(
        sm,
        beneficiary_id=no_consent,
        payer_id=no_consent,
        pack_id=pack,
        card_id=seed_saved_card(sm, no_consent),
        cap=100,
        consented_at=None,
    )
    no_card = add_user(sm, Role.student)
    seed_auto_topup(
        sm,
        beneficiary_id=no_card,
        payer_id=no_card,
        pack_id=pack,
        card_id=None,
        cap=100,
        consented_at=NOW,
    )
    client = admin_client(sm, admin)
    preview = client.get(f"{P}/packs/{pack}/price-impact", params={"priceMinor": 20_000})
    assert preview.json() == {"autoTopupCount": 1, "capBelowPriceCount": 1}
    body = _edit_pack(sm, admin, pack, price_minor=20_000, is_active=False)
    # A deactivated pack charges nobody, so nothing is affected; the enabled count stays real.
    assert (body["autoTopupCount"], body["autoTopupCapBelowPriceCount"]) == (3, 0)
    [row] = audit_rows(sm, "catalogue.credit_pack.update")
    assert row.after is not None
    assert row.after["impact"] == {"autoTopupsAffected": 0, "autoTopupsCapBelowPrice": 0}


def test_a_rename_leaves_the_audit_diff_to_the_changed_fields_only(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm, price_minor=10_000)
    _customer(sm, pack, cap=100)
    _edit_pack(sm, admin, pack, price_minor=10_000)
    [row] = audit_rows(sm, "catalogue.credit_pack.update")
    assert row.before is not None and row.after is not None
    assert row.before["impact"] == row.after["impact"]
    changed = {k for k in row.after if row.before.get(k) != row.after[k]}
    assert changed == {"name"}


def test_a_deactivated_pack_enqueues_nothing_and_leaves_the_setting_alone(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm, price_minor=10_000)
    user = _customer(sm, pack)
    before = _setting(sm, user)
    _edit_pack(sm, admin, pack, price_minor=10_000, is_active=False)
    assert _enqueue(sm, user) is None
    after = _setting(sm, user)
    assert (after.enabled, after.armed, after.crossing_seq) == (True, True, before.crossing_seq)
    assert after.last_payment_id is None
