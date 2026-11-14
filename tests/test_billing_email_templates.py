"""The two merchant-charge failure emails and their notice helpers (Paymob billing Phase 06 T2).

The templates are pure (no database). The helpers write the outbox row in the caller's
transaction and run on a throwaway Postgres database.
"""

from __future__ import annotations

import html
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from lemely.db.billing_notices import (
    enqueue_auto_topup_card_missing,
    enqueue_auto_topup_failed,
    enqueue_auto_topup_phone_required,
    enqueue_extra_seats_charge_failed,
)
from lemely.db.email_outbox_repo import count_sent_since_in_session, mark_in_session
from lemely.db.models.enums import EmailOutboxStatus, NotificationType, Role
from lemely.db.models.tutoring import EmailOutbox
from lemely.io.notify_email import (
    BILLING_EMAIL_TEMPLATES,
    EMAIL_TEMPLATES,
    AutoTopupCardMissing,
    AutoTopupFailed,
    AutoTopupPhoneRequired,
    EmailContext,
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
SETTING_ID = uuid.UUID("99999999-9999-4999-8999-999999999999")

TEMPLATES: tuple[tuple[str, type[EmailContext], str], ...] = (
    ("auto_topup_failed", AutoTopupFailed, "payment_id"),
    ("extra_seats_charge_failed", ExtraSeatsChargeFailed, "subscription_id"),
    ("auto_topup_card_missing", AutoTopupCardMissing, "setting_id"),
    ("auto_topup_phone_required", AutoTopupPhoneRequired, "setting_id"),
)


#: The exact context each template accepts (the allow-list the outbox validates against).
_CONTEXT_FIELDS: dict[str, frozenset[str]] = {
    "auto_topup_failed": frozenset({"payment_id"}),
    "extra_seats_charge_failed": frozenset({"subscription_id", "grace_days"}),
    "auto_topup_card_missing": frozenset({"setting_id"}),
    "auto_topup_phone_required": frozenset({"setting_id"}),
}


def _context(key: str) -> dict[str, object]:
    ids = {"payment_id": PAYMENT_ID, "setting_id": SETTING_ID}
    return {key: str(ids.get(key, SUBSCRIPTION_ID))}


# -- the templates ---------------------------------------------------------------


@pytest.mark.parametrize(("name", "cls", "key"), TEMPLATES)
def test_both_failure_templates_are_registered_billing_templates(
    name: str, cls: type[EmailContext], key: str
) -> None:
    assert EMAIL_TEMPLATES[name] is cls
    assert cls.template == name
    assert cls.notification_type is NotificationType.billing
    assert name in BILLING_EMAIL_TEMPLATES  # the daily-cap exemption (UD-9) keys on this set
    assert cls.context_fields == _CONTEXT_FIELDS[name]
    assert cls.button == "Open billing"


def test_subjects_are_the_briefed_ones() -> None:
    assert AutoTopupFailed.subject == "Auto top-up could not charge your card"
    assert ExtraSeatsChargeFailed.subject == "Your extra seats payment failed"


@pytest.mark.parametrize(("name", "cls", "key"), TEMPLATES)
def test_context_refuses_extra_and_missing_keys_and_bad_ids(
    name: str, cls: type[EmailContext], key: str
) -> None:
    good = _context(key)
    # The seats mail also carries the grace; a row queued before that field reads as 3 days.
    expected = {**good, "grace_days": 3} if name == "extra_seats_charge_failed" else good
    assert validate_context(name, good) == expected
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


def test_card_missing_copy_says_the_card_was_removed_not_that_a_charge_failed() -> None:
    mail = AutoTopupCardMissing(setting_id=SETTING_ID)
    assert "your saved card was removed" in mail.lead()
    assert "auto top-up is turned off" in mail.lead().lower()
    everything = f"{mail.subject} {mail.lead()} {mail.detail()}".lower()
    assert "fail" not in everything
    assert "could not charge" not in everything
    assert mail.path() == "/billing"


def test_phone_copy_says_to_add_a_number_not_that_a_charge_failed() -> None:
    mail = AutoTopupPhoneRequired(setting_id=SETTING_ID)
    assert "no mobile number" in mail.lead()
    everything = f"{mail.subject} {mail.lead()} {mail.detail()}".lower()
    assert "fail" not in everything
    assert "could not charge" not in everything
    assert "card" not in everything  # it is the number, not the card, that is missing
    assert mail.path() == "/billing"


def test_seats_copy_says_when_the_seats_go() -> None:
    mail = ExtraSeatsChargeFailed(subscription_id=SUBSCRIPTION_ID)
    assert "within 3 days" in mail.lead()
    assert "extra seats are removed" in mail.lead()
    assert mail.detail() is not None
    assert "end of the month" in mail.detail()  # type: ignore[operator]
    assert mail.path() == "/billing"


# Nothing in these two mails is filled in at send time (the context id is never rendered), so the
# whole mail is pinned. Any edit to the copy shows up here and has to be read by a person.
_NOTICE = "Open Lemely to see the details."
_LINK = f"{BASE_URL}/billing"
_COPY: dict[str, tuple[str, str, str]] = {
    "auto_topup_failed": (
        "Auto top-up could not charge your card",
        "We could not charge your saved card for an auto top-up, so auto top-up is turned off.",
        "You can check your card and turn auto top-up back on in billing settings.",
    ),
    "auto_topup_card_missing": (
        "Auto top-up is off: your saved card was removed",
        "Auto top-up is turned off because your saved card was removed.",
        "Add a card and turn auto top-up back on in billing settings.",
    ),
    "auto_topup_phone_required": (
        "Auto top-up is off: add a mobile number",
        "Auto top-up is turned off because there is no mobile number on your account.",
        "Add a mobile number to your account, then turn auto top-up back on in billing settings.",
    ),
    "extra_seats_charge_failed": (
        "Your extra seats payment failed",
        "We could not charge your card for your extra student seats. We will try again each "
        "day; if no payment succeeds within 3 days, the extra seats are removed.",
        "Students beyond your plan's included seats then keep their seat until the end of "
        "the month.",
    ),
}
_HTML = (
    '<!doctype html><html lang="en"><body style="margin:0;padding:24px;background:#f6f7f9;'
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    'color:#1f2933;"><div style="max-width:480px;margin:0 auto;background:#ffffff;'
    'border-radius:12px;padding:32px;"><h1 style="margin:0 0 16px;font-size:20px;'
    'line-height:1.3;">@SUBJECT@</h1><p style="margin:0 0 16px;font-size:15px;line-height:1.55;">'
    '@LEAD@</p><p style="margin:0 0 16px;font-size:15px;line-height:1.55;">@DETAIL@</p>'
    '<p style="margin:0 0 24px;"><a href="@LINK@" style="display:inline-block;'
    "background:#1f2933;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:8px;"
    'font-size:15px;font-weight:600;">Open billing</a></p><p style="margin:0 0 8px;'
    'font-size:13px;line-height:1.5;color:#52606d;">If the button does not work, copy this '
    'link into your browser:</p><p style="margin:0 0 24px;font-size:13px;line-height:1.5;'
    'word-break:break-all;"><a href="@LINK@" style="color:#2563eb;">@LINK@</a></p>'
    '<p style="margin:0;font-size:13px;line-height:1.5;color:#52606d;">@NOTICE@</p>'
    "</div></body></html>"
)


def _expected(name: str) -> tuple[str, str, str]:
    subject, lead, detail = _COPY[name]
    text = f"{subject}\n\n{lead}\n\n{detail}\n\n{_LINK}\n\n{_NOTICE}\n"
    html_body = (
        _HTML.replace("@SUBJECT@", subject)
        .replace("@LEAD@", html.escape(lead))
        .replace("@DETAIL@", html.escape(detail))
        .replace("@LINK@", _LINK)
        .replace("@NOTICE@", _NOTICE)
    )
    return subject, html_body, text


@pytest.mark.parametrize(("name", "cls", "key"), TEMPLATES)
def test_the_exact_subject_text_and_html_of_each_mail(
    name: str, cls: type[EmailContext], key: str
) -> None:
    assert render_email(name, _context(key), app_base_url=BASE_URL) == _expected(name)


# What the billing mail may never carry: a number (the one "3 days" of the seats mail is the only
# allowed digit), a currency word or sign, a card brand, the processor's name, a refund promise.
_ALLOWED_DIGITS = "within 3 days"
_FORBIDDEN = (
    re.compile(r"\d"),
    re.compile(r"\b(?:pounds?|piasters?|egp|le)\b|جنيه|[£$€]", re.IGNORECASE),
    re.compile(r"\b(?:visa|master\s?card|meeza|amex|american express)\b", re.IGNORECASE),
    re.compile(r"paymob", re.IGNORECASE),
    re.compile(r"refund", re.IGNORECASE),
    re.compile(r"\bretry\b", re.IGNORECASE),
)
# The auto top-up failure turns auto top-up off and never retries, so that mail may not promise
# one. The seats mail does retry daily (its copy is pinned above), so the phrase is its own.
_NO_TRY_AGAIN = re.compile(r"\btry\s+again\b", re.IGNORECASE)


def _violations(name: str, mail: str, *, digits: bool = True) -> list[str]:
    """The forbidden patterns ``mail`` matches (``digits=False`` for markup with style numbers)."""
    scanned = mail.replace(_ALLOWED_DIGITS, "")
    patterns = list(_FORBIDDEN if digits else _FORBIDDEN[1:])
    if name.startswith("auto_topup"):
        patterns.append(_NO_TRY_AGAIN)
    return [pattern.pattern for pattern in patterns if pattern.search(scanned)]


@pytest.mark.parametrize(("name", "cls", "key"), TEMPLATES)
def test_rendered_mail_carries_no_amount_card_brand_processor_or_promise(
    name: str, cls: type[EmailContext], key: str
) -> None:
    subject, html_body, text = render_email(name, _context(key), app_base_url=BASE_URL)

    assert _violations(name, subject) == []
    assert _violations(name, text) == []
    assert _violations(name, html_body, digits=False) == []
    # The id sits in no part of the mail: only the fixed words and the link do.
    assert str(PAYMENT_ID) not in text + html_body
    assert str(SUBSCRIPTION_ID) not in text + html_body
    assert str(SETTING_ID) not in text + html_body


@pytest.mark.parametrize(
    ("name", "leaked"),
    [
        ("extra_seats_charge_failed", "Charged 150 EGP"),
        ("extra_seats_charge_failed", "150 pounds"),
        ("extra_seats_charge_failed", "1,500"),
        ("extra_seats_charge_failed", "150.00"),
        ("extra_seats_charge_failed", "E£150"),
        ("extra_seats_charge_failed", "£12"),
        ("extra_seats_charge_failed", "150 جنيه"),
        ("extra_seats_charge_failed", "card ****4242"),
        ("extra_seats_charge_failed", "your Visa card"),
        ("extra_seats_charge_failed", "your Mastercard"),
        ("extra_seats_charge_failed", "your Meeza card"),
        ("extra_seats_charge_failed", "via Paymob"),
        ("extra_seats_charge_failed", "we will refund you"),
        ("extra_seats_charge_failed", "we will retry"),
        ("extra_seats_charge_failed", "within 3 days and 4 more"),
        ("auto_topup_failed", "We will try again tomorrow"),
    ],
)
def test_the_copy_guard_itself_catches_what_it_forbids(name: str, leaked: str) -> None:
    assert _violations(name, leaked) != []


def test_the_copy_guard_lets_the_one_allowed_phrase_and_the_seats_retry_through() -> None:
    seats_lead = _COPY["extra_seats_charge_failed"][1]
    assert _violations("extra_seats_charge_failed", seats_lead) == []
    # "try again" is only refused in the auto top-up mail.
    assert _violations("auto_topup_failed", seats_lead) != []


@pytest.mark.parametrize(
    ("cls", "name", "key", "leak"),
    [
        (
            ExtraSeatsChargeFailed,
            "extra_seats_charge_failed",
            "subscription_id",
            "We could not charge 150 pounds to your Visa card for your extra student seats.",
        ),
        (
            AutoTopupFailed,
            "auto_topup_failed",
            "payment_id",
            "We could not charge your saved card for an auto top-up, so auto top-up is turned "
            "off. We will try again tomorrow and charge 1,500 to your Visa.",
        ),
    ],
    ids=["seats-amount-and-brand", "auto-topup-retry-amount-and-brand"],
)
def test_an_edited_lead_goes_red_through_both_the_guard_and_the_pin(
    monkeypatch: pytest.MonkeyPatch,
    cls: type[EmailContext],
    name: str,
    key: str,
    leak: str,
) -> None:
    monkeypatch.setattr(cls, "lead", lambda self: leak)

    rendered = render_email(name, _context(key), app_base_url=BASE_URL)

    assert rendered != _expected(name)
    assert _violations(name, rendered[2]) != []


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
    grace_days: int = 3,
) -> bool:
    with sm.begin() as session:
        return enqueue_extra_seats_charge_failed(
            session,
            payer_user_id=payer,
            subscription_id=subscription_id,
            first_attempt_id=first_attempt_id,
            grace_days=grace_days,
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


def test_card_missing_helper_queues_one_row_per_disable(pg: sessionmaker[Session]) -> None:
    payer = seed_user(pg, Role.parent)
    setting = uuid.uuid4()

    def queue(seq: int) -> bool:
        with pg.begin() as session:
            return enqueue_auto_topup_card_missing(
                session, payer_user_id=payer, setting_id=setting, crossing_seq=seq
            )

    assert (queue(1), queue(1), queue(2)) == (True, False, True)
    rows = _outbox(pg, payer)
    assert [r.template for r in rows] == ["auto_topup_card_missing"] * 2
    assert rows[0].context == {"setting_id": str(setting)}
    assert {r.dedupe_key for r in rows} == {
        f"auto_topup_card_missing:{setting}:1",
        f"auto_topup_card_missing:{setting}:2",
    }


def test_phone_helper_queues_one_row_per_disable_to_the_payer(pg: sessionmaker[Session]) -> None:
    payer = seed_user(pg, Role.parent)
    setting = uuid.uuid4()

    def queue(seq: int) -> bool:
        with pg.begin() as session:
            return enqueue_auto_topup_phone_required(
                session, payer_user_id=payer, setting_id=setting, crossing_seq=seq
            )

    assert (queue(1), queue(1), queue(2)) == (True, False, True)
    rows = _outbox(pg, payer)
    assert [r.template for r in rows] == ["auto_topup_phone_required"] * 2
    assert rows[0].context == {"setting_id": str(setting)}
    assert {r.dedupe_key for r in rows} == {
        f"auto_topup_phone_required:{setting}:1",
        f"auto_topup_phone_required:{setting}:2",
    }


def test_phone_notice_respects_billing_notifications_off(pg: sessionmaker[Session]) -> None:
    quiet = seed_user(pg, Role.parent)
    _switch_billing_off(pg, quiet)
    with pg.begin() as session:
        assert (
            enqueue_auto_topup_phone_required(
                session, payer_user_id=quiet, setting_id=uuid.uuid4(), crossing_seq=1
            )
            is False
        )
    assert _outbox(pg, quiet) == []


def test_card_missing_notice_respects_billing_notifications_off(pg: sessionmaker[Session]) -> None:
    quiet = seed_user(pg, Role.parent)
    _switch_billing_off(pg, quiet)
    with pg.begin() as session:
        assert (
            enqueue_auto_topup_card_missing(
                session, payer_user_id=quiet, setting_id=uuid.uuid4(), crossing_seq=1
            )
            is False
        )
    assert _outbox(pg, quiet) == []


def test_seats_helper_queues_one_row_to_the_payer(pg: sessionmaker[Session]) -> None:
    payer = seed_user(pg, Role.teacher)
    subscription, first = uuid.uuid4(), uuid.uuid4()

    assert _seats(pg, payer, subscription, first) is True

    (row,) = _outbox(pg, payer)
    assert row.template == "extra_seats_charge_failed"
    assert row.context == {"subscription_id": str(subscription), "grace_days": 3}
    assert row.dedupe_key == f"extra_seats_failed:{first}"


def test_seats_context_is_the_id_and_the_grace_and_an_old_row_reads_as_three_days() -> None:
    assert ExtraSeatsChargeFailed.context_fields == frozenset({"subscription_id", "grace_days"})
    old = validate_context("extra_seats_charge_failed", {"subscription_id": str(SUBSCRIPTION_ID)})
    assert ExtraSeatsChargeFailed.model_validate(old).grace_days == 3  # queued before the field
    for bad in (0, 8, -1, "three"):
        with pytest.raises(InvalidEmailContext):
            validate_context(
                "extra_seats_charge_failed",
                {"subscription_id": str(SUBSCRIPTION_ID), "grace_days": bad},
            )


@pytest.mark.parametrize("days", [1, 2, 3, 7])
def test_the_seats_row_carries_the_grace_the_failure_started(
    pg: sessionmaker[Session], days: int
) -> None:
    payer = seed_user(pg, Role.teacher)

    assert _seats(pg, payer, uuid.uuid4(), uuid.uuid4(), days) is True

    (row,) = _outbox(pg, payer)
    assert row.context["grace_days"] == days
    lead = ExtraSeatsChargeFailed.model_validate(
        {**row.context, "subscription_id": str(SUBSCRIPTION_ID)}
    ).lead()
    assert f"within {days} day" in lead
    assert ("each day" in lead) == (days > 1)


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
