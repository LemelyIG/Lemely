"""T18 review I1: the platform's terms-move cancel goes out before Paymob can charge early.

A plan whose Paymob anchor sits ``MAX_GRACE_DAYS`` days before our period end (a renewal paid on
the last retry day of a longest-retry plan) is charged that early. The hold on the platform's
cancel must end before then, or Paymob charges a plan the payer was told will end.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.subscription_rules import MAX_GRACE_DAYS
from lemely.db.subscription_repo import EARLY_CHARGE_WINDOW
from tests.subscription_fixtures import ensure_billing_settings, throwaway_database
from tests.team_db import emptied_after
from tests.test_terms_change_moves import END, _fixed_cancelled, _push_cancels, _sub

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def sm(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    ensure_billing_settings(_database)
    yield from emptied_after(_database)
    with _database.begin() as session:
        session.execute(sa.text("TRUNCATE paymob_events CASCADE"))


def test_the_cancel_is_pushed_before_paymobs_anchor_seven_days_early(
    sm: sessionmaker[Session],
) -> None:
    _, sid, _ = _fixed_cancelled(sm)
    paymob_charge = END - timedelta(days=MAX_GRACE_DAYS)
    pushed = _push_cancels(sm, paymob_charge - timedelta(minutes=10))
    assert pushed.calls_to("cancel_subscription")
    assert _sub(sm, sid).paymob_cancelled_at is not None


def test_the_hold_opens_exactly_at_the_window(sm: sessionmaker[Session]) -> None:
    _, sid, _ = _fixed_cancelled(sm)
    before = END - EARLY_CHARGE_WINDOW - timedelta(minutes=1)
    assert _push_cancels(sm, before).calls_to("cancel_subscription") == []
    assert _sub(sm, sid).paymob_cancelled_at is None
    assert _push_cancels(sm, END - EARLY_CHARGE_WINDOW).calls_to("cancel_subscription")
