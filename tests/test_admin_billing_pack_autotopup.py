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

from lemely.db.auto_topup_repo import AUTO_TOPUP_DEDUPE_PREFIX, enqueue_auto_topup
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
from tests.merchant_charge_fixtures import seed_auto_topup, seed_payment_row, seed_saved_card

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
    assert row.after["autoTopupsAffected"] == 1
    assert row.after["autoTopupsCapBelowPrice"] == 1


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
    assert (row.after["autoTopupsAffected"], row.after["autoTopupsCapBelowPrice"]) == (2, 1)


def test_a_payment_queued_before_the_change_keeps_its_amount(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    pack = add_credit_pack(sm, units=500, price_minor=10_000)
    user = _customer(sm, pack)
    queued = _enqueue(sm, user)
    assert queued is not None
    _edit_pack(sm, admin, pack, units=600, price_minor=20_000)
    payment = _payment(sm, queued)
    assert (payment.amount_minor, payment.grant_units) == (10_000, 500)
    assert payment.status is PaymentStatus.created
    # Another queued top-up (an earlier crossing) is equally untouched.
    other = seed_payment_row(
        sm,
        payer_id=user,
        beneficiary_id=user,
        purpose=PaymentPurpose.auto_topup,
        amount_minor=10_000,
        status=PaymentStatus.failed,
        credit_pack_id=pack,
        dedupe_key=f"{AUTO_TOPUP_DEDUPE_PREFIX}{user}:{uuid.uuid4()}",
        created_at=NOW,
    )
    _edit_pack(sm, admin, pack, units=600, price_minor=30_000)
    assert _payment(sm, other).amount_minor == 10_000


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
