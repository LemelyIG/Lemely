"""Subscription notices go to the payer through the email outbox, once per event (Phase 05).

Real Postgres (a throwaway ``create_all`` database). Nothing here sends mail; the outbox row
is the whole observable effect.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.billing_notices import SubscriptionNoticeKind, enqueue_subscription_notice
from lemely.db.models.billing import PlanAudience, PlanTier, Subscription
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.io.notify_email import render_email
from tests.team_db import add_user, team_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

WHEN = datetime(2026, 12, 10, 9, 0, tzinfo=UTC)
LATER = WHEN + timedelta(days=3)
ALL_NOTICES: tuple[SubscriptionNoticeKind, ...] = (
    "renewed",
    "payment_failed",
    "expired",
    "cancelled",
    "credited",
)


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


def seed_tier(sm: sessionmaker[Session]) -> uuid.UUID:
    tid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            PlanTier(
                id=tid,
                code=f"t-{tid.hex[:8]}",
                name="Plan",
                price_minor=10_000,
                currency="EGP",
                interval=PlanInterval.monthly,
                audience=PlanAudience.student,
            )
        )
    return tid


def seed_subscription(
    sm: sessionmaker[Session],
    *,
    user_id: uuid.UUID,
    payer_id: uuid.UUID | None,
    is_manually_activated: bool = False,
) -> uuid.UUID:
    sid = uuid.uuid4()
    tier_id = seed_tier(sm)
    with sm.begin() as session:
        session.add(
            Subscription(
                id=sid,
                user_id=user_id,
                plan_tier_id=tier_id,
                payer_user_id=payer_id,
                status=SubscriptionStatus.active,
                is_manually_activated=is_manually_activated,
            )
        )
    return sid


def queue(
    sm: sessionmaker[Session],
    subscription_id: uuid.UUID,
    notice: SubscriptionNoticeKind,
    effective_at: datetime = WHEN,
) -> bool:
    with sm.begin() as session:
        subscription = session.get(Subscription, subscription_id)
        assert subscription is not None
        return enqueue_subscription_notice(
            session, subscription=subscription, notice=notice, effective_at=effective_at
        )


def outbox_for(sm: sessionmaker[Session], *recipients: uuid.UUID) -> list[EmailOutbox]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(EmailOutbox)
                .where(EmailOutbox.recipient_user_id.in_(recipients))
                .order_by(EmailOutbox.created_at, EmailOutbox.id)
            )
        )


def test_notice_goes_to_the_payer_not_the_beneficiary(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = add_user(pg_sessionmaker, Role.parent)
    child = add_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=child, payer_id=parent)

    assert queue(pg_sessionmaker, sid, "renewed")

    assert outbox_for(pg_sessionmaker, child) == []
    rows = outbox_for(pg_sessionmaker, parent)
    assert [(row.recipient_user_id, row.template) for row in rows] == [
        (parent, "subscription_notice")
    ]
    assert rows[0].context == {
        "subscription_id": str(sid),
        "notice": "renewed",
        "effective_at": "2026-12-10T09:00:00Z",
    }


def test_the_stored_context_renders_without_price_or_card_detail(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = add_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=payer, payer_id=payer)
    assert queue(pg_sessionmaker, sid, "payment_failed")

    (row,) = outbox_for(pg_sessionmaker, payer)
    _, html_body, text = render_email(
        row.template, row.context, app_base_url="https://staging.lemelyig.example"
    )

    assert "10 Dec 2026" in text
    assert "EGP" not in html_body
    assert "EGP" not in text
    assert "10000" not in text
    assert "10,000" not in text


def test_the_same_notice_is_queued_once(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer = add_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=payer, payer_id=payer)

    with pg_sessionmaker.begin() as session:
        subscription = session.get(Subscription, sid)
        assert subscription is not None
        first = enqueue_subscription_notice(
            session, subscription=subscription, notice="expired", effective_at=WHEN
        )
        second = enqueue_subscription_notice(
            session, subscription=subscription, notice="expired", effective_at=WHEN
        )

    assert (first, second) == (True, False)
    assert len(outbox_for(pg_sessionmaker, payer)) == 1


def test_the_same_instant_in_another_offset_is_still_the_same_notice(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = add_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=payer, payer_id=payer)
    cairo = timezone(timedelta(hours=2))

    assert queue(pg_sessionmaker, sid, "renewed", WHEN)
    assert not queue(pg_sessionmaker, sid, "renewed", WHEN.astimezone(cairo))

    (row,) = outbox_for(pg_sessionmaker, payer)
    assert row.dedupe_key == f"subscription:{sid}:renewed:{WHEN.isoformat()}"
    assert len(row.dedupe_key) <= 200


def test_two_different_dates_for_one_notice_both_queue(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = add_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=payer, payer_id=payer)

    assert queue(pg_sessionmaker, sid, "payment_failed", WHEN)
    assert queue(pg_sessionmaker, sid, "payment_failed", LATER)

    keys = {row.dedupe_key for row in outbox_for(pg_sessionmaker, payer)}
    assert len(keys) == 2


def test_two_different_notices_for_one_subscription_both_queue(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = add_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=payer, payer_id=payer)

    results = [queue(pg_sessionmaker, sid, notice) for notice in ALL_NOTICES]

    assert results == [True] * len(ALL_NOTICES)
    notices = sorted(str(row.context["notice"]) for row in outbox_for(pg_sessionmaker, payer))
    assert notices == sorted(ALL_NOTICES)


def test_manual_subscription_without_payer_queues_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = add_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(
        pg_sessionmaker, user_id=user, payer_id=None, is_manually_activated=True
    )

    assert not queue(pg_sessionmaker, sid, "renewed")

    assert outbox_for(pg_sessionmaker, user) == []


def test_opted_out_payer_gets_nothing(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer = add_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=payer, payer_id=payer)
    # No API toggle exists for `billing`: switch it off in the row directly.
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.text("INSERT INTO notification_preferences (user_id, billing) VALUES (:u, false)"),
            {"u": payer},
        )
    assert NotificationPreferencesService(pg_sessionmaker).get(payer).billing is False

    assert not queue(pg_sessionmaker, sid, "renewed")

    assert outbox_for(pg_sessionmaker, payer) == []


def test_one_payers_opt_out_does_not_silence_another_payer(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    quiet = add_user(pg_sessionmaker, Role.parent)
    loud = add_user(pg_sessionmaker, Role.parent)
    quiet_sid = seed_subscription(
        pg_sessionmaker, user_id=add_user(pg_sessionmaker, Role.student), payer_id=quiet
    )
    loud_sid = seed_subscription(
        pg_sessionmaker, user_id=add_user(pg_sessionmaker, Role.student), payer_id=loud
    )
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.text("INSERT INTO notification_preferences (user_id, billing) VALUES (:u, false)"),
            {"u": quiet},
        )

    assert not queue(pg_sessionmaker, quiet_sid, "renewed")
    assert queue(pg_sessionmaker, loud_sid, "renewed")

    assert outbox_for(pg_sessionmaker, quiet) == []
    assert len(outbox_for(pg_sessionmaker, loud)) == 1


def test_a_naive_effective_at_is_refused_and_queues_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = add_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=payer, payer_id=payer)

    with pytest.raises(ValueError, match="timezone"):
        queue(pg_sessionmaker, sid, "renewed", datetime(2026, 12, 10, 9, 0))

    assert outbox_for(pg_sessionmaker, payer) == []


def test_one_payer_with_two_subscriptions_gets_both_notices_for_the_same_event(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = add_user(pg_sessionmaker, Role.parent)
    first = seed_subscription(
        pg_sessionmaker, user_id=add_user(pg_sessionmaker, Role.student), payer_id=parent
    )
    second = seed_subscription(
        pg_sessionmaker, user_id=add_user(pg_sessionmaker, Role.student), payer_id=parent
    )

    assert queue(pg_sessionmaker, first, "renewed", WHEN)
    assert queue(pg_sessionmaker, second, "renewed", WHEN)

    rows = outbox_for(pg_sessionmaker, parent)
    assert {row.context["subscription_id"] for row in rows} == {str(first), str(second)}
    assert len({row.dedupe_key for row in rows}) == 2


def test_the_credited_notice_queues_once_per_payment_instant(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = add_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=payer, payer_id=payer)

    assert queue(pg_sessionmaker, sid, "credited", WHEN)
    assert not queue(pg_sessionmaker, sid, "credited", WHEN)
    assert queue(pg_sessionmaker, sid, "credited", LATER)

    assert [row.context["notice"] for row in outbox_for(pg_sessionmaker, payer)] == [
        "credited",
        "credited",
    ]
