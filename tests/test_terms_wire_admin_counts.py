"""``liveSubscriptionCount`` and ``pendingMoves`` on the admin tier DTO (P08-T20 review finding 5).

Both count the notice job's pool (``subscribers_to_move``'s), so the "waiting to move" badge drains
and the "customers get an email" warning is true: complimentary, manual, cancelling, plan-changing
and pending-checkout rows are never emailed or moved, so they are in neither number.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.billing import Subscription
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.plan_terms_repo import subscribers_to_move
from tests.admin_billing_db import (
    add_plan_tier,
    add_subscription,
    add_user,
    admin_client,
    billing_database,
    emptied_after,
)
from tests.subscription_fixtures import edit_tier_terms

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


def _row(sm: sessionmaker[Session], admin: uuid.UUID, code: str) -> dict[str, object]:
    body = admin_client(sm, admin).get(f"{P}/catalogue").json()
    return next(t for t in body["planTiers"] if t["code"] == code)


def test_counts_are_the_notice_pool_and_pending_moves_is_subscribers_to_move(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm, code="counted", price_minor=10_000)
    other = add_plan_tier(sm, code="target", price_minor=5_000)
    add_subscription(sm, add_user(sm), tier)  # moves
    add_subscription(sm, add_user(sm), tier, status=SubscriptionStatus.past_due)  # moves
    add_subscription(sm, add_user(sm), tier, manual=True)  # a manual activation does not renew
    add_subscription(sm, add_user(sm), tier, status=SubscriptionStatus.pending_first_payment)
    cancelling = add_subscription(sm, add_user(sm), tier)
    changing = add_subscription(sm, add_user(sm), tier)
    complimentary = add_subscription(sm, add_user(sm), tier)
    with sm.begin() as session:
        for sid, values in (
            (cancelling, {"cancel_at_period_end": True}),
            (changing, {"pending_plan_tier_id": other}),
            (complimentary, {"payer_user_id": None}),
        ):
            session.execute(sa.update(Subscription).where(Subscription.id == sid).values(**values))
    edit_tier_terms(sm, tier, price_minor=15_000)
    row = _row(sm, admin, "counted")
    assert (row["liveSubscriptionCount"], row["pendingMoves"]) == (2, 2)
    with sm() as session:
        assert subscribers_to_move(session, tier) == row["pendingMoves"]


def test_the_waiting_badge_drains_when_the_subscribers_have_moved(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm, code="draining", price_minor=10_000)
    sid = add_subscription(sm, add_user(sm), tier)
    add_subscription(sm, add_user(sm), tier, manual=True)  # never moves
    edit_tier_terms(sm, tier, price_minor=15_000)
    row = _row(sm, admin, "draining")
    assert (row["liveSubscriptionCount"], row["pendingMoves"]) == (1, 1)
    with sm.begin() as session:  # the renewal moved the subscriber
        session.execute(
            sa.update(Subscription).where(Subscription.id == sid).values(terms_version=2)
        )
    row = _row(sm, admin, "draining")
    assert (row["liveSubscriptionCount"], row["pendingMoves"]) == (1, 0)  # drained


def test_a_tier_whose_only_rows_are_complimentary_has_no_customers_to_warn(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm, code="gifted", price_minor=10_000)
    add_subscription(sm, add_user(sm), tier, manual=True)
    edit_tier_terms(sm, tier, price_minor=15_000)
    row = _row(sm, admin, "gifted")
    assert (row["liveSubscriptionCount"], row["pendingMoves"]) == (0, 0)
