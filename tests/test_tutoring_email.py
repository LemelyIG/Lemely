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
from lemely.io.notify_email import MockTransactionalEmailProvider
from lemely.runtime.config import EmailSettings, Settings
from lemely.web.tutoring_email import (
    MOCK_WARNING,
    deliver_tutoring_email,
    doctor_lines,
    email_delivery_mode,
)
from tests import test_email_outbox_repo as _outbox
from tests.test_email_outbox_repo import NOW, RecordingProvider, _enqueue, _rows, _user

if TYPE_CHECKING:
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
    assert row.attempts == 1
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
        1,
    )


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


def test_email_delivery_mode_reports_mock_without_api_key() -> None:
    assert email_delivery_mode(Settings()) == "mock"
    keyed = Settings(email=EmailSettings(api_key="re_test"))  # type: ignore[arg-type]
    assert email_delivery_mode(keyed) == "provider"


def test_doctor_lines_warn_on_mock() -> None:
    mock_lines = doctor_lines(Settings())
    assert any(MOCK_WARNING in line for line in mock_lines)
    assert any(line.startswith("WARNING") for line in mock_lines)

    keyed = Settings(email=EmailSettings(api_key="re_test"))  # type: ignore[arg-type]
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
