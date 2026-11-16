"""T18 re-review N1: no seat or upgrade charge while the next period is already paid.

Paymob renews at its own anchor, which after a late retry can be days before our period end. Our
renewal then moves ``current_period_start`` to the old end, so for those days the subscription
points at a period that has not started. A quote prorates against that future period, charges the
full price, and the settle voids it as ``period_rolled`` (credits instead of seats). Nothing is
charged while ``now < current_period_start``: the refusal is ``period_not_started`` with the date
changes open again.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from lemely.db.merchant_charge_repo import MerchantChargeError, register_amount_pusher
from lemely.db.models.billing_ops import CreditConversionRate
from tests.subscription_fixtures import throwaway_database
from tests.test_merchant_charge_seats import (
    PERIOD_END,
    _buy,
    _CheckoutClient,
    _quote,
    _refused,
    _seat_tier,
    _sub,
    _teacher,
    _update_sub,
    _upgrade_checkout,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

#: Paymob renewed 7 days early: the current period is already the next one, ``[END, END + 30 d]``.
OPENS_AT = PERIOD_END
INSIDE_GAP = PERIOD_END - timedelta(days=5)


@pytest.fixture(autouse=True)
def _no_amount_pusher() -> Iterator[None]:
    register_amount_pusher(None)
    yield
    register_amount_pusher(None)


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        with factory.begin() as session:
            session.add(CreditConversionRate(currency="EGP", units_per_minor=Decimal("0.01")))
        yield factory


def _renewed_early(sm: sessionmaker[Session]) -> dict[str, object]:
    scene = _teacher(sm)
    _update_sub(
        sm,
        scene,
        current_period_start=OPENS_AT,
        current_period_end=OPENS_AT + timedelta(days=30),
    )
    return dict(scene)


def test_seats_are_refused_before_the_period_starts_and_nothing_is_charged(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _renewed_early(sm)
    client = _CheckoutClient()
    caught = _refused(sm, client, scene, 2, "period_not_started", now=INSIDE_GAP)  # type: ignore[arg-type]
    assert caught.detail == {"opens_at": OPENS_AT.isoformat()}
    assert _sub(sm, scene).extra_seats == 1  # type: ignore[arg-type]


def test_the_seat_quote_is_refused_too(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _renewed_early(sm)
    with pytest.raises(MerchantChargeError) as caught:
        _quote(sm, _CheckoutClient(), scene, 2, now=INSIDE_GAP)  # type: ignore[arg-type]
    assert caught.value.code == "period_not_started"


def test_an_upgrade_quote_and_checkout_are_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _renewed_early(sm)
    target = _seat_tier(sm, price=40_000, seat_price=5_000)
    with pytest.raises(MerchantChargeError) as caught:
        _upgrade_checkout(sm, _CheckoutClient(), scene, target, now=INSIDE_GAP)  # type: ignore[arg-type]
    assert caught.value.code == "period_not_started"
    assert caught.value.detail == {"opens_at": OPENS_AT.isoformat()}


def test_the_upgrade_quote_service_call_is_refused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    from lemely.db.merchant_charge_repo import MerchantChargeService
    from tests.paymob_fixtures import PAYMOB_SETTINGS

    sm = pg_sessionmaker
    scene = _renewed_early(sm)
    target = _seat_tier(sm, price=40_000, seat_price=5_000)
    with sm() as session, pytest.raises(MerchantChargeError) as caught:
        MerchantChargeService(session, _CheckoutClient(), PAYMOB_SETTINGS).quote_upgrade(
            subscription_id=scene["subscription_id"],  # type: ignore[arg-type]
            actor_user_id=scene["payer_id"],  # type: ignore[arg-type]
            plan_tier_id=target,
            now=INSIDE_GAP,
        )
    assert caught.value.code == "period_not_started"


def test_changes_open_again_when_the_period_starts(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _renewed_early(sm)
    assert _buy(sm, _CheckoutClient(), scene, 1, now=OPENS_AT + timedelta(days=1))  # type: ignore[arg-type]


def test_an_ordinary_mid_period_purchase_is_not_affected(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    assert _buy(sm, _CheckoutClient(), scene, 1)
