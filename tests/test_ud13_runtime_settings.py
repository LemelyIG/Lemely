"""UD-13 runtime readers (Phase 07 T15): signup validity, conversion rate, seat-ceiling schemas.

Credit validity at grant time, the seat ceiling in the services and the public catalogue's
``creditValidityMonths`` have their cases beside the code they exercise
(``test_billing_callbacks``, ``test_subscription_first_payment``, ``test_merchant_charge_seats``,
``test_subscription_drift``, ``test_web_billing``); this file holds the rest.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from lemely.core import billing_defaults
from lemely.db.models.billing import CreditPack
from lemely.db.models.billing_ops import CreditConversionRate
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageGrant
from lemely.db.subscription_repo import credit_units_for_amount
from lemely.db.usage_catalogue_repo import (
    SIGNUP_STUDENT_PACK,
    SIGNUP_TEACHER_PACK,
    ensure_usage_catalogue,
    grant_signup_allowance,
)
from lemely.web.schemas_billing_charges import SeatReductionRequest
from lemely.web.schemas_subscriptions import SubscriptionCheckoutRequestDTO
from tests.usage_helpers import NOW, seed_user

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session, sessionmaker


def _set_signup_days(sm: sessionmaker[Session], code: str, days: int | None) -> None:
    with sm.begin() as session:
        ensure_usage_catalogue(session, now=NOW)
        session.execute(
            sa.update(CreditPack).where(CreditPack.code == code).values(signup_validity_days=days)
        )


def _signup_grant(sm: sessionmaker[Session], role: Role) -> UsageGrant:
    user: uuid.UUID = seed_user(sm, role)
    with sm.begin() as session:
        grant = grant_signup_allowance(session, user_id=user, role=role, now=NOW)
        assert grant is not None
        session.expunge(grant)
        return grant


# -- signup validity (A9) -----------------------------------------------------------------------


def test_the_teacher_signup_seed_is_thirty_days(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    assert billing_defaults.TEACHER_SIGNUP_VALIDITY_DAYS == 30
    with migrated_sessionmaker.begin() as session:
        ensure_usage_catalogue(session, now=NOW)
    with migrated_sessionmaker() as session:
        days = session.scalar(
            sa.select(CreditPack.signup_validity_days).where(CreditPack.code == SIGNUP_TEACHER_PACK)
        )
        assert days == 30
        assert (
            session.scalar(
                sa.select(CreditPack.signup_validity_days).where(
                    CreditPack.code == SIGNUP_STUDENT_PACK
                )
            )
            is None
        )
    assert _signup_grant(migrated_sessionmaker, Role.teacher).expires_at == NOW + timedelta(days=30)


def test_an_edited_teacher_signup_validity_sets_the_expiry(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _set_signup_days(migrated_sessionmaker, SIGNUP_TEACHER_PACK, 45)
    grant = _signup_grant(migrated_sessionmaker, Role.teacher)
    assert grant.expires_at == NOW + timedelta(days=45)


def test_a_teacher_pack_without_validity_never_expires(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _set_signup_days(migrated_sessionmaker, SIGNUP_TEACHER_PACK, None)
    grant = _signup_grant(migrated_sessionmaker, Role.teacher)
    assert grant.expires_at is None
    assert grant.visible is True


def test_the_student_allowance_follows_the_same_rule_and_stays_hidden(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    never = _signup_grant(migrated_sessionmaker, Role.student)
    assert never.expires_at is None
    assert never.visible is False
    _set_signup_days(migrated_sessionmaker, SIGNUP_STUDENT_PACK, 10)
    timed = _signup_grant(migrated_sessionmaker, Role.student)
    assert timed.expires_at == NOW + timedelta(days=10)
    assert timed.visible is False


# -- the credit conversion rate (A12) -----------------------------------------------------------


def _rate(sm: sessionmaker[Session], units_per_minor: str | None, currency: str = "EGP") -> None:
    with sm.begin() as session:
        session.execute(
            sa.delete(CreditConversionRate).where(CreditConversionRate.currency == currency)
        )
        if units_per_minor is not None:
            session.add(
                CreditConversionRate(currency=currency, units_per_minor=Decimal(units_per_minor))
            )


def test_conversion_rounds_down_never_to_nearest(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _rate(migrated_sessionmaker, "0.5")
    with migrated_sessionmaker() as session:
        assert credit_units_for_amount(session, amount_minor=10_000, currency="EGP") == 5_000
        assert credit_units_for_amount(session, amount_minor=10_001, currency="EGP") == 5_000
        # 5001.5: round-half-even would grant 5002, more than was paid for.
        assert credit_units_for_amount(session, amount_minor=10_003, currency="EGP") == 5_001


def test_a_fraction_of_one_unit_converts_to_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _rate(migrated_sessionmaker, "0.9")
    with migrated_sessionmaker() as session:
        # 0.9 units: rounding to nearest would grant one, flooring grants none.
        assert credit_units_for_amount(session, amount_minor=1, currency="EGP") is None
        assert credit_units_for_amount(session, amount_minor=2, currency="EGP") == 1
    _rate(migrated_sessionmaker, "0.4")
    with migrated_sessionmaker() as session:
        assert credit_units_for_amount(session, amount_minor=1, currency="EGP") is None


def test_no_rate_row_means_no_conversion_in_any_currency(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _rate(migrated_sessionmaker, None)
    with migrated_sessionmaker() as session:
        assert credit_units_for_amount(session, amount_minor=10_000, currency="EGP") is None
        assert credit_units_for_amount(session, amount_minor=10_000, currency="USD") is None


def test_an_edit_applies_to_the_next_conversion_with_no_cache(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _rate(migrated_sessionmaker, "0.5")
    with migrated_sessionmaker() as session:
        assert credit_units_for_amount(session, amount_minor=100, currency="EGP") == 50
    _rate(migrated_sessionmaker, "2")
    with migrated_sessionmaker() as session:
        assert credit_units_for_amount(session, amount_minor=100, currency="EGP") == 200


# -- the seat ceiling in the request schemas (A15, N1) -----------------------------------------


def test_the_request_schemas_bound_seats_by_the_sanity_limit_not_the_old_constant() -> None:
    assert (
        SubscriptionCheckoutRequestDTO.model_validate(
            {"planTierId": "5f1f3f0e-0000-4000-8000-000000000001", "extraSeats": 10_000}
        ).extraSeats
        == 10_000
    )
    assert SeatReductionRequest.model_validate({"extraSeats": 10_000}).extraSeats == 10_000
    for over in (10_001, -1):
        with pytest.raises(ValidationError):
            SeatReductionRequest.model_validate({"extraSeats": over})
        with pytest.raises(ValidationError):
            SubscriptionCheckoutRequestDTO.model_validate(
                {"planTierId": "5f1f3f0e-0000-4000-8000-000000000001", "extraSeats": over}
            )
