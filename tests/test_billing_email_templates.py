"""The two merchant-charge failure emails and their notice helpers (Paymob billing Phase 06 T2).

The templates are pure (no database). The helpers write the outbox row in the caller's
transaction and run on a throwaway Postgres database.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from lemely.db.billing_notices import (
    enqueue_auto_topup_failed,
    enqueue_extra_seats_charge_failed,
)
from lemely.db.email_outbox_repo import count_sent_since_in_session, mark_in_session
from lemely.db.models.enums import EmailOutboxStatus, NotificationType, Role
from lemely.db.models.tutoring import EmailOutbox
from lemely.io.notify_email import (
    BILLING_EMAIL_TEMPLATES,
    EMAIL_TEMPLATES,
    AutoTopupFailed,
    ExtraSeatsChargeFailed,
    InvalidEmailContext,
    render_email,
    validate_context,
)
from tests.paymob_fixtures import seed_user
from tests.subscription_fixtures import throwaway_database

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

BASE_URL = "https://staging.lemelyig.example"
PAYMENT_ID = uuid.UUID("77777777-7777-4777-8777-777777777777")
SUBSCRIPTION_ID = uuid.UUID("88888888-8888-4888-8888-888888888888")

TEMPLATES: tuple[tuple[str, type[AutoTopupFailed] | type[ExtraSeatsChargeFailed], str], ...] = (
    ("auto_topup_failed", AutoTopupFailed, "payment_id"),
    ("extra_seats_charge_failed", ExtraSeatsChargeFailed, "subscription_id"),
)


def _context(key: str) -> dict[str, object]:
    return {key: str(PAYMENT_ID if key == "payment_id" else SUBSCRIPTION_ID)}


# -- the templates ---------------------------------------------------------------


@pytest.mark.parametrize(("name", "cls", "key"), TEMPLATES)
def test_both_failure_templates_are_registered_billing_templates(
    name: str, cls: type[AutoTopupFailed] | type[ExtraSeatsChargeFailed], key: str
) -> None:
    assert EMAIL_TEMPLATES[name] is cls
    assert cls.template == name
    assert cls.notification_type is NotificationType.billing
    assert name in BILLING_EMAIL_TEMPLATES  # the daily-cap exemption (UD-9) keys on this set
    assert cls.context_fields == frozenset({key})
    assert cls.button == "Open billing"


def test_subjects_are_the_briefed_ones() -> None:
    assert AutoTopupFailed.subject == "Auto top-up could not charge your card"
    assert ExtraSeatsChargeFailed.subject == "Your extra seats payment failed"


@pytest.mark.parametrize(("name", "cls", "key"), TEMPLATES)
def test_context_refuses_extra_and_missing_keys_and_bad_ids(
    name: str, cls: type[AutoTopupFailed] | type[ExtraSeatsChargeFailed], key: str
) -> None:
    good = _context(key)
    assert validate_context(name, good) == good
    with pytest.raises(InvalidEmailContext):
        validate_context(name, {**good, "amount_minor": 100})
    with pytest.raises(InvalidEmailContext):
        validate_context(name, {})
    with pytest.raises(InvalidEmailContext):
        validate_context(name, {key: "not-a-uuid"})
    with pytest.raises(ValidationError):
        cls.model_validate({**good, "card": "4111"})


def test_auto_topup_copy_says_it_is_off_and_where_to_turn_it_on() -> None:
    mail = AutoTopupFailed(payment_id=PAYMENT_ID)
    assert "auto top-up is turned off" in mail.lead()
    assert mail.detail() is not None
    assert "billing settings" in mail.detail()  # type: ignore[operator]
    assert mail.path() == "/billing"


def test_seats_copy_says_when_the_seats_go() -> None:
    mail = ExtraSeatsChargeFailed(subscription_id=SUBSCRIPTION_ID)
    assert "within 3 days" in mail.lead()
    assert "extra seats are removed" in mail.lead()
    assert mail.detail() is not None
    assert "end of the month" in mail.detail()  # type: ignore[operator]
    assert mail.path() == "/billing"


# The words the billing mail may never carry: an amount, a currency, a processor name, a refund
# or retry promise, a masked card number.
_FORBIDDEN = (
    re.compile(r"\d\s*(?:EGP|LE\b|E£|£)", re.IGNORECASE),
    re.compile(r"(?:EGP|E£|£|\$)\s*\d", re.IGNORECASE),
    re.compile(r"[x*•]{2,}\s*\d{4}", re.IGNORECASE),
    re.compile(r"\b\d{4}\b"),
    re.compile(r"paymob", re.IGNORECASE),
    re.compile(r"refund", re.IGNORECASE),
    re.compile(r"\bretry\b", re.IGNORECASE),
)


@pytest.mark.parametrize(("name", "cls", "key"), TEMPLATES)
def test_rendered_mail_carries_no_amount_card_processor_or_promise(
    name: str, cls: type[AutoTopupFailed] | type[ExtraSeatsChargeFailed], key: str
) -> None:
    subject, html_body, text = render_email(name, _context(key), app_base_url=BASE_URL)

    assert f"{BASE_URL}/billing" in html_body
    assert text.startswith(subject)
    # The id sits in no part of the mail: only the fixed words and the link do.
    assert str(PAYMENT_ID) not in text
    assert str(SUBSCRIPTION_ID) not in text
    for pattern in _FORBIDDEN:
        assert pattern.search(subject) is None, pattern.pattern
        assert pattern.search(text) is None, pattern.pattern
        assert pattern.search(html_body) is None, pattern.pattern


@pytest.mark.parametrize(
    "leaked",
    ["Charged 150 EGP", "E£150", "£12", "card ****4242", "via Paymob", "we will refund you"],
)
def test_the_copy_guard_itself_catches_what_it_forbids(leaked: str) -> None:
    assert any(pattern.search(leaked) for pattern in _FORBIDDEN)


# -- the helpers -----------------------------------------------------------------


@pytest.fixture(scope="module")
def pg() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


def _outbox(sm: sessionmaker[Session], recipient: uuid.UUID) -> list[EmailOutbox]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(EmailOutbox)
                .where(EmailOutbox.recipient_user_id == recipient)
                .order_by(EmailOutbox.created_at, EmailOutbox.id)
            )
        )


def _auto_topup(sm: sessionmaker[Session], payer: uuid.UUID, payment_id: uuid.UUID) -> bool:
    with sm.begin() as session:
        return enqueue_auto_topup_failed(session, payer_user_id=payer, payment_id=payment_id)


def _seats(
    sm: sessionmaker[Session],
    payer: uuid.UUID,
    subscription_id: uuid.UUID,
    first_attempt_id: uuid.UUID,
) -> bool:
    with sm.begin() as session:
        return enqueue_extra_seats_charge_failed(
            session,
            payer_user_id=payer,
            subscription_id=subscription_id,
            first_attempt_id=first_attempt_id,
        )


def _switch_billing_off(sm: sessionmaker[Session], user_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text("INSERT INTO notification_preferences (user_id, billing) VALUES (:u, false)"),
            {"u": user_id},
        )


def test_auto_topup_helper_queues_one_row_to_the_payer(pg: sessionmaker[Session]) -> None:
    payer = seed_user(pg, Role.parent)
    other = seed_user(pg, Role.student)
    payment = uuid.uuid4()

    assert _auto_topup(pg, payer, payment) is True

    assert _outbox(pg, other) == []
    (row,) = _outbox(pg, payer)
    assert row.template == "auto_topup_failed"
    assert row.context == {"payment_id": str(payment)}
    assert row.dedupe_key == f"auto_topup_failed:{payment}"


def test_seats_helper_queues_one_row_to_the_payer(pg: sessionmaker[Session]) -> None:
    payer = seed_user(pg, Role.teacher)
    subscription, first = uuid.uuid4(), uuid.uuid4()

    assert _seats(pg, payer, subscription, first) is True

    (row,) = _outbox(pg, payer)
    assert row.template == "extra_seats_charge_failed"
    assert row.context == {"subscription_id": str(subscription)}
    assert row.dedupe_key == f"extra_seats_failed:{first}"


def test_the_same_failure_is_queued_once(pg: sessionmaker[Session]) -> None:
    payer = seed_user(pg, Role.teacher)
    payment, subscription, first = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    assert (_auto_topup(pg, payer, payment), _auto_topup(pg, payer, payment)) == (True, False)
    assert (_seats(pg, payer, subscription, first), _seats(pg, payer, subscription, first)) == (
        True,
        False,
    )

    assert sorted(row.template for row in _outbox(pg, payer)) == [
        "auto_topup_failed",
        "extra_seats_charge_failed",
    ]


def test_two_different_payments_give_two_auto_topup_rows(pg: sessionmaker[Session]) -> None:
    payer = seed_user(pg, Role.student)

    assert _auto_topup(pg, payer, uuid.uuid4()) is True
    assert _auto_topup(pg, payer, uuid.uuid4()) is True

    rows = _outbox(pg, payer)
    assert len(rows) == 2
    assert len({row.dedupe_key for row in rows}) == 2


def test_two_different_first_attempts_give_two_seat_rows(pg: sessionmaker[Session]) -> None:
    payer = seed_user(pg, Role.teacher)
    subscription = uuid.uuid4()

    assert _seats(pg, payer, subscription, uuid.uuid4()) is True
    assert _seats(pg, payer, subscription, uuid.uuid4()) is True

    rows = _outbox(pg, payer)
    assert len(rows) == 2
    assert len({row.dedupe_key for row in rows}) == 2


@pytest.mark.parametrize(
    "queue",
    [
        lambda sm, payer: _auto_topup(sm, payer, uuid.uuid4()),
        lambda sm, payer: _seats(sm, payer, uuid.uuid4(), uuid.uuid4()),
    ],
    ids=["auto_topup", "extra_seats"],
)
def test_a_payer_with_billing_notifications_off_gets_nothing(
    pg: sessionmaker[Session],
    queue: Callable[[sessionmaker[Session], uuid.UUID], bool],
) -> None:
    quiet = seed_user(pg, Role.parent)
    loud = seed_user(pg, Role.parent)
    _switch_billing_off(pg, quiet)

    assert queue(pg, quiet) is False
    assert queue(pg, loud) is True

    assert _outbox(pg, quiet) == []
    assert len(_outbox(pg, loud)) == 1


def test_failure_rows_are_not_counted_by_the_daily_cap_query(pg: sessionmaker[Session]) -> None:
    payer = seed_user(pg, Role.teacher)
    assert _auto_topup(pg, payer, uuid.uuid4())
    assert _seats(pg, payer, uuid.uuid4(), uuid.uuid4())
    sent_at = datetime.now(UTC)
    with pg.begin() as session:
        for row in session.scalars(
            sa.select(EmailOutbox).where(EmailOutbox.recipient_user_id == payer)
        ):
            mark_in_session(
                session,
                row.id,
                status=EmailOutboxStatus.sent,
                last_error=None,
                sent_at=sent_at,
            )

    with pg() as session:
        sent_rows = session.scalar(
            sa.select(sa.func.count())
            .select_from(EmailOutbox)
            .where(
                EmailOutbox.recipient_user_id == payer,
                EmailOutbox.status == EmailOutboxStatus.sent,
            )
        )
        assert sent_rows == 2  # non-vacuity: both rows are sent and inside the window
        assert count_sent_since_in_session(session, sent_at.replace(year=2000)) == 0
