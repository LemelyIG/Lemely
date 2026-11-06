"""The tutoring email job's recipient rules and the mock's honesty (SPEC §b.4, SC-6, SC-15, EM-1).

``tests/test_email_outbox_repo.py`` covers claiming, the cap and first-attempt-only; this file
covers who is *not* mailed, what the mock records, and the startup/doctor reporting.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
import structlog.testing

from lemely.db.models.enums import EmailOutboxStatus, Role
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.users import User
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.io.notify_email import MockTransactionalEmailProvider
from lemely.runtime.config import EmailSettings, Settings
from lemely.web.scheduled_notifications import run_jobs
from lemely.web.tutoring_email import (
    MOCK_WARNING,
    deliver_tutoring_email,
    doctor_lines,
    email_delivery_mode,
)
from tests import test_email_outbox_repo as _outbox
from tests.test_email_outbox_repo import NOW, RecordingProvider, _enqueue, _rows, _user

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

PLACEHOLDER_DOMAIN = "@parents.lemely.local"

# The throwaway-database fixture lives beside the outbox tests; assigning it here makes pytest
# collect it for this module under the same name.
pg_sessionmaker = _outbox.pg_sessionmaker


def _run(sm: sessionmaker[Session], provider: object, *, cap: int = 60, now: datetime = NOW) -> int:
    return deliver_tutoring_email(
        sessionmaker=sm,
        provider=provider,  # type: ignore[arg-type]
        daily_cap=cap,
        now=lambda: now,
    )


def test_email_mock_marks_skipped_not_sent(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _user(pg_sessionmaker, email="parent@example.org")
    _enqueue(pg_sessionmaker, user, template="booking_requested_family")

    with structlog.testing.capture_logs() as logs:
        handled = _run(pg_sessionmaker, MockTransactionalEmailProvider())

    assert handled == 1
    (row,) = _rows(pg_sessionmaker)
    assert row.status is EmailOutboxStatus.skipped
    assert row.last_error == "mock_provider"
    assert row.attempts == 0  # nothing was sent, so nothing was attempted
    assert row.sent_at is None
    rendered = json.dumps(logs, default=str)
    assert str(row.id) in rendered
    assert "booking_requested_family" in rendered
    assert "parent@example.org" not in rendered


def test_a_mock_skip_does_not_count_against_the_daily_cap(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    for index in range(3):
        _enqueue(pg_sessionmaker, _user(pg_sessionmaker), key=f"m:{index}")
    _run(pg_sessionmaker, MockTransactionalEmailProvider(), cap=1)
    assert {r.last_error for r in _rows(pg_sessionmaker)} == {"mock_provider"}


def test_email_skipped_for_unverified_recipient(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _user(pg_sessionmaker, verified=False)
    _enqueue(pg_sessionmaker, user)
    provider = RecordingProvider()

    assert _run(pg_sessionmaker, provider) == 1

    (row,) = _rows(pg_sessionmaker)
    assert provider.calls == []
    assert (row.status, row.last_error, row.attempts) == (
        EmailOutboxStatus.skipped,
        "unverified_recipient",
        0,
    )


def test_email_skipped_when_preference_turned_off_after_enqueue(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """R2: the preference is checked again at send time, so switching a type off cancels it."""
    user = _user(pg_sessionmaker, email="tutor@example.org")
    assert _enqueue(pg_sessionmaker, user) is True  # booking_requested -> booking_request
    NotificationPreferencesService(pg_sessionmaker).set(user, booking_request=False)
    provider = RecordingProvider()

    assert _run(pg_sessionmaker, provider) == 1

    (row,) = _rows(pg_sessionmaker)
    assert provider.calls == []
    assert (row.status, row.last_error, row.attempts) == (
        EmailOutboxStatus.skipped,
        "preference_off",
        0,
    )


def test_preference_off_wins_over_the_mock_reason(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _user(pg_sessionmaker)
    _enqueue(pg_sessionmaker, user)
    NotificationPreferencesService(pg_sessionmaker).set(user, booking_request=False)
    _run(pg_sessionmaker, MockTransactionalEmailProvider())
    (row,) = _rows(pg_sessionmaker)
    assert row.last_error == "preference_off"


def test_a_different_type_switched_off_does_not_block_the_mail(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _user(pg_sessionmaker)
    _enqueue(pg_sessionmaker, user)
    NotificationPreferencesService(pg_sessionmaker).set(user, booking_update=False)
    provider = RecordingProvider()
    _run(pg_sessionmaker, provider)
    assert len(provider.calls) == 1


def test_placeholder_parent_address_skipped(pg_sessionmaker: sessionmaker[Session]) -> None:
    """A phone-only parent's synthesised address is never mailed, even if verified (EM-6)."""
    user = _user(pg_sessionmaker, email=f"{uuid.uuid4().hex}{PLACEHOLDER_DOMAIN}", role=Role.parent)
    _enqueue(pg_sessionmaker, user, template="booking_requested_family")
    provider = RecordingProvider()

    assert _run(pg_sessionmaker, provider) == 1

    (row,) = _rows(pg_sessionmaker)
    assert provider.calls == []
    assert (row.status, row.last_error) == (EmailOutboxStatus.skipped, "placeholder_address")


def test_placeholder_domain_matches_the_parent_repo_constant() -> None:
    from lemely.db import parent_repo
    from lemely.db.email_outbox_repo import PLACEHOLDER_EMAIL_DOMAIN

    assert PLACEHOLDER_EMAIL_DOMAIN == parent_repo._PLACEHOLDER_EMAIL_DOMAIN == PLACEHOLDER_DOMAIN


def test_a_deleted_recipient_cascades_the_row_away(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _user(pg_sessionmaker)
    _enqueue(pg_sessionmaker, user)
    with pg_sessionmaker.begin() as session:
        session.execute(sa.delete(User).where(User.id == user))
    provider = RecordingProvider()
    assert _run(pg_sessionmaker, provider) == 0
    assert provider.calls == []


def test_the_sent_count_window_is_a_rolling_24_hours_from_now(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _user(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        session.add(
            EmailOutbox(
                recipient_user_id=user,
                template="booking_requested",
                context={},
                dedupe_key="earlier",
                status=EmailOutboxStatus.sent,
                attempts=1,
                sent_at=NOW,
            )
        )
    _enqueue(pg_sessionmaker, user, key="later")
    provider = RecordingProvider()

    # cap 1 reached by the earlier send at NOW; 25 hours later it has left the window.
    _run(pg_sessionmaker, provider, cap=1, now=NOW + timedelta(hours=25))
    assert len(provider.calls) == 1


# -- one bad row never blocks the queue (final review finding 1) -----------------
#
# Before the fix, an unknown template raised ``KeyError`` from the preference lookup, the tick
# rolled back, ``run_jobs`` logged ``sweep_job_failed``, and the same oldest row was claimed first
# again on every tick: nothing behind it, safety mails included, was ever delivered.


def _age(sm: sessionmaker[Session], key: str, *, hours: int) -> None:
    with sm.begin() as session:
        session.execute(
            sa.update(EmailOutbox)
            .where(EmailOutbox.dedupe_key == key)
            .values(created_at=NOW - timedelta(hours=hours))
        )


def _tick(sm: sessionmaker[Session], provider: object) -> int | None:
    """One sweeper tick's email job, through the same runner the sweeper uses."""
    return run_jobs([("deliver_tutoring_email", lambda: _run(sm, provider))])[
        "deliver_tutoring_email"
    ]


def test_an_unknown_template_row_fails_and_the_rows_behind_it_are_delivered(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A row left by a later release (after a rollback) or a manual insert: ``failed``, once."""
    bad = _user(pg_sessionmaker, email="bad.row@example.org")
    good = _user(pg_sessionmaker, email="good.row@example.org")
    with pg_sessionmaker.begin() as session:
        session.add(
            EmailOutbox(
                recipient_user_id=bad,
                template="booking_rescheduled_from_a_later_release",
                context={"booking_id": str(uuid.uuid4())},
                dedupe_key="bad",
            )
        )
    _enqueue(pg_sessionmaker, good, key="good", template="parent_linked")
    _age(pg_sessionmaker, "bad", hours=2)  # the oldest row, so it is claimed first
    _age(pg_sessionmaker, "good", hours=1)
    provider = RecordingProvider()

    handled = [_tick(pg_sessionmaker, provider) for _ in range(3)]

    rows = {r.dedupe_key: r for r in _rows(pg_sessionmaker)}
    assert (rows["bad"].status, rows["bad"].last_error, rows["bad"].sent_at) == (
        EmailOutboxStatus.failed,
        "unknown_template",
        None,
    )
    assert rows["good"].status is EmailOutboxStatus.sent
    assert [call[0] for call in provider.calls] == ["good.row@example.org"]
    assert handled == [2, 0, 0]  # never None: the job itself no longer throws


def _first_call_raises(
    monkeypatch: pytest.MonkeyPatch, name: str, make_error: Callable[..., object]
) -> None:
    """Replace ``lemely.web.tutoring_email.<name>`` with one whose first call fails."""
    import lemely.web.tutoring_email as job

    real = getattr(job, name)
    calls: list[int] = []

    def wrapper(*args: object, **kwargs: object) -> object:
        calls.append(1)
        if len(calls) == 1:
            return make_error(*args, **kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(job, name, wrapper)


def _two_rows_first_older(sm: sessionmaker[Session]) -> None:
    _enqueue(sm, _user(sm, email="first.parent@example.org"), key="first")
    _enqueue(sm, _user(sm, email="second.parent@example.org"), key="second")
    _age(sm, "first", hours=2)
    _age(sm, "second", hours=1)


def test_a_failing_renderer_fails_only_its_row(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unexpected exception while rendering one row's mail fails that row and nothing else.

    The reason is the exception's class name only: the message may carry the address.
    """
    _two_rows_first_older(pg_sessionmaker)

    def renderer_crash(*_: object, **__: object) -> object:
        raise RuntimeError("template engine crashed rendering for first.parent@example.org")

    _first_call_raises(monkeypatch, "validate_context", renderer_crash)
    provider = RecordingProvider()

    with structlog.testing.capture_logs() as logs:
        assert _tick(pg_sessionmaker, provider) == 2

    rows = {r.dedupe_key: r for r in _rows(pg_sessionmaker)}
    assert (rows["first"].status, rows["first"].last_error) == (
        EmailOutboxStatus.failed,
        "error:RuntimeError",
    )
    assert rows["second"].status is EmailOutboxStatus.sent
    assert [call[0] for call in provider.calls] == ["second.parent@example.org"]
    rendered = json.dumps(logs, default=str)
    assert str(rows["first"].id) in rendered
    assert "first.parent@example.org" not in rendered


def test_a_database_error_inside_one_row_fails_only_that_row(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SQL error aborts the transaction; the row is still marked and the next one delivered."""
    _two_rows_first_older(pg_sessionmaker)

    def broken_lookup(session: Session, *_: object) -> object:
        return session.execute(sa.text("SELECT 1 / 0"))

    _first_call_raises(monkeypatch, "recipient_in_session", broken_lookup)
    provider = RecordingProvider()

    assert _tick(pg_sessionmaker, provider) == 2

    rows = {r.dedupe_key: r for r in _rows(pg_sessionmaker)}
    assert rows["first"].status is EmailOutboxStatus.failed
    assert rows["first"].last_error is not None
    assert rows["first"].last_error.startswith("error:")
    assert "@" not in rows["first"].last_error
    assert rows["second"].status is EmailOutboxStatus.sent


def test_email_delivery_mode_reports_mock_without_api_key() -> None:
    # Explicit [email] section: an exported LEMELY_EMAIL__API_KEY must not change the answer.
    assert email_delivery_mode(Settings.model_construct(email=EmailSettings())) == "mock"
    keyed = Settings.model_construct(email=EmailSettings(api_key="re_test"))  # type: ignore[arg-type]
    assert email_delivery_mode(keyed) == "provider"


def test_doctor_lines_warn_on_mock() -> None:
    mock_lines = doctor_lines(Settings.model_construct(email=EmailSettings()))
    assert any(MOCK_WARNING in line for line in mock_lines)
    assert any(line.startswith("WARNING") for line in mock_lines)

    keyed = Settings.model_construct(email=EmailSettings(api_key="re_test"))  # type: ignore[arg-type]
    provider_lines = doctor_lines(keyed)
    assert provider_lines
    assert not any("WARNING" in line for line in provider_lines)
    assert not any("re_test" in line for line in provider_lines)  # never prints the key


def test_the_mock_warning_says_what_is_true() -> None:
    lowered = MOCK_WARNING.lower()
    assert "mock" in lowered
    assert "no email" in lowered or "not sent" in lowered or "no mail" in lowered
    assert "api_key" in lowered
    assert "!" not in MOCK_WARNING


def test_deliver_tutoring_email_signature_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        deliver_tutoring_email(None, None, 60, lambda: NOW)  # type: ignore[misc]
