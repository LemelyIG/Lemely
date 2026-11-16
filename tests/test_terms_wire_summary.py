"""``pendingTermsChange.seatsToRemove`` and the payer-cancel wire (P08-T20 review findings 2, 3).

``seatsToRemove`` is the notice email's and the renewal's count: active seats only, so it falls to
zero once the teacher has removed the students. After a payer cancels, the summary carries
``cancelAtPeriodEnd`` with no ``cancelReason`` and the pending change is still there: the screen
reads those two to stay consistent with "Ends DATE".
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.billing import PlanAudience, Subscription
from lemely.db.models.enums import Role
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.plan_terms_repo import queue_terms_change_notices
from lemely.db.teacher_team_repo import TeacherTeamService
from tests.subscription_fixtures import edit_tier_terms
from tests.team_db import add_seat, add_user, emptied_after, team_database
from tests.test_web_billing_summary import (
    NOW,
    _client,
    _set_pending_terms,
    _sub,
    _tier,
    _view,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

LATER = NOW + timedelta(days=13)


@pytest.fixture(scope="module")
def wire_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(wire_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(wire_db)


def _teacher_with_seats(
    sm: sessionmaker[Session], *, seats: int, included: int, extra_seat_price: int = 0
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    teacher = add_user(sm, Role.teacher)
    tier = _tier(
        sm,
        audience=PlanAudience.teacher,
        included_seats=included,
        extra_seat_price_minor=extra_seat_price,
    )
    sub = _sub(sm, user=teacher, tier=tier, payer=teacher)
    members = [
        add_seat(sm, teacher_id=teacher, student_id=add_user(sm, Role.student))
        for _ in range(seats)
    ]
    return teacher, tier, sub, members


def _change(sm: sessionmaker[Session], user: uuid.UUID, role: Role) -> dict[str, object]:
    change = _view(_client(sm, user, role))["pendingTermsChange"]
    assert isinstance(change, dict)
    return change


def test_seats_to_remove_counts_active_seats_over_the_new_capacity(
    sm: sessionmaker[Session],
) -> None:
    teacher, tier, sub, _ = _teacher_with_seats(sm, seats=5, included=5)
    edit_tier_terms(sm, tier, included_seats=3)
    _set_pending_terms(sm, sub, version=2, effective_at=LATER)
    assert _change(sm, teacher, Role.teacher)["seatsToRemove"] == 2


def test_seats_to_remove_falls_to_zero_once_the_students_are_leaving(
    sm: sessionmaker[Session],
) -> None:
    """The review's probe: a seat already leaving is not counted, as in the renewal's shed."""
    teacher, tier, sub, members = _teacher_with_seats(sm, seats=5, included=5)
    edit_tier_terms(sm, tier, included_seats=3)
    _set_pending_terms(sm, sub, version=2, effective_at=LATER)
    with sm.begin() as session:  # the teacher removes two students, as the app does
        team = TeacherTeamService(session)
        for member in members[:2]:
            team.request_removal(member, now=NOW)
    assert _change(sm, teacher, Role.teacher)["seatsToRemove"] == 0
    seats = _client(sm, teacher, Role.teacher).get("/api/billing/summary").json()["seats"]
    assert seats["used"] == 5  # active plus leaving: the number the browser used to subtract


def test_seats_to_remove_counts_extra_seats_only_while_the_new_terms_sell_them(
    sm: sessionmaker[Session],
) -> None:
    teacher, tier, sub, _ = _teacher_with_seats(sm, seats=6, included=3, extra_seat_price=500)
    with sm.begin() as session:
        session.execute(sa.update(Subscription).where(Subscription.id == sub).values(extra_seats=2))
    edit_tier_terms(sm, tier, included_seats=2)  # capacity 2 + 2 extra = 4: remove 2
    _set_pending_terms(sm, sub, version=2, effective_at=LATER)
    assert _change(sm, teacher, Role.teacher)["seatsToRemove"] == 2
    edit_tier_terms(sm, tier, included_seats=2, extra_seat_price_minor=0)  # no seats sold now
    _set_pending_terms(sm, sub, version=3, effective_at=LATER)
    assert _change(sm, teacher, Role.teacher)["seatsToRemove"] == 4  # the extras no longer count


def test_seats_to_remove_is_null_for_a_plan_that_holds_no_seats(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    tier = _tier(sm, price_minor=9_900)
    sub = _sub(sm, user=student, tier=tier, payer=student)
    edit_tier_terms(sm, tier, price_minor=12_000)
    _set_pending_terms(sm, sub, version=2, effective_at=LATER)
    assert _change(sm, student, Role.student)["seatsToRemove"] is None


def test_seats_to_remove_is_the_same_number_the_email_carries(sm: sessionmaker[Session]) -> None:
    """One definition: the notice job's ``seats_over`` and the summary's ``seatsToRemove``."""
    teacher, tier, _, _ = _teacher_with_seats(sm, seats=5, included=5)
    edit_tier_terms(sm, tier, included_seats=3)
    queue_terms_change_notices(sm, now=NOW, amount_updatable=True)
    with sm() as session:
        mail = session.scalars(
            sa.select(EmailOutbox).where(EmailOutbox.template == "plan_terms_change")
        ).one()
    assert mail.context["seats_over"] == _change(sm, teacher, Role.teacher)["seatsToRemove"] == 2


def test_after_a_payer_cancel_the_summary_says_cancelling_with_no_reason_and_keeps_the_move(
    sm: sessionmaker[Session],
) -> None:
    """Finding 3: read ``cancelAtPeriodEnd`` and ``cancelReason`` together. A cancel with no
    reason is a person's (payer, admin or suspension), and the screen must not announce a change
    for a plan that ends first; only ``plan_terms_changed`` is the move ending the plan."""
    student = add_user(sm, Role.student)
    tier = _tier(sm, price_minor=9_900)
    sub = _sub(sm, user=student, tier=tier, payer=student)
    edit_tier_terms(sm, tier, price_minor=12_000)
    _set_pending_terms(sm, sub, version=2, effective_at=LATER, cancel=True, cancel_source="payer")
    view = _view(_client(sm, student, Role.student))
    assert (view["cancelAtPeriodEnd"], view["cancelReason"]) == (True, None)
    assert isinstance(view["pendingTermsChange"], dict)  # kept, so a revert can still be told
    _set_pending_terms(
        sm, sub, version=2, effective_at=LATER, cancel=True, cancel_source="platform_terms"
    )
    view = _view(_client(sm, student, Role.student))
    assert (view["cancelAtPeriodEnd"], view["cancelReason"]) == (True, "plan_terms_changed")
