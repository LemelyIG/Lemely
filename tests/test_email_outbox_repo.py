"""The email outbox and its delivery job (SPEC §b.4, SC-6, SC-15, SC-25, decision log row 12).

Real Postgres (a throwaway database built with ``create_all``), the mock and a
recording provider. Nothing here sends mail and nothing calls Gemini.
"""

from __future__ import annotations

import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.email_outbox_repo import enqueue_in_session
from lemely.db.models import import_all_models
from lemely.db.models.enums import EmailOutboxStatus, NotificationType, Role
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.users import User
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.io.notify_email import EMAIL_TEMPLATES, InvalidEmailContext
from lemely.runtime.config import DatabaseSettings
from lemely.runtime.errors import ExternalServiceError
from lemely.web.tutoring_email import deliver_tutoring_email
from tests.test_notify_email import VALID, spec_b4_rows

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

import_all_models()

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    server_url = make_url(base_url).set(database="postgres")
    probe = create_engine(server_url)
    try:
        with probe.connect():
            pass
    except OperationalError:
        pytest.skip("local Postgres not reachable")
    finally:
        probe.dispose()
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


class RecordingProvider:
    """A provider that 'delivers' (``delivers_out_of_band``) and records what it was given."""

    delivers_out_of_band = True

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, object], uuid.UUID | None]] = []
        self._fail_with = fail_with

    def send(
        self,
        to: str,
        template: str,
        context: Mapping[str, object],
        *,
        outbox_id: uuid.UUID | None = None,
    ) -> None:
        self.calls.append((to, template, dict(context), outbox_id))
        if self._fail_with is not None:
            raise self._fail_with


def _user(
    sm: sessionmaker[Session],
    *,
    verified: bool = True,
    email: str | None = None,
    role: Role = Role.teacher,
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(
                id=uid,
                email=email or f"{uid}@example.org",
                role=role,
                email_verified_at=NOW - timedelta(days=30) if verified else None,
            )
        )
    return uid


def _enqueue(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    *,
    key: str | None = None,
    template: str = "booking_requested",
) -> bool:
    with sm.begin() as session:
        return enqueue_in_session(
            session,
            recipient_user_id=user,
            template=template,
            context=VALID[template],
            dedupe_key=key or f"test:{uuid.uuid4()}",
        )


def _rows(sm: sessionmaker[Session]) -> list[EmailOutbox]:
    with sm() as session:
        return list(session.scalars(sa.select(EmailOutbox).order_by(EmailOutbox.created_at)))


def _deliver(
    sm: sessionmaker[Session],
    provider: RecordingProvider,
    *,
    cap: int = 60,
    batch: int = 20,
    now: datetime = NOW,
) -> int:
    return deliver_tutoring_email(
        sessionmaker=sm, provider=provider, daily_cap=cap, now=lambda: now, batch=batch
    )


# -- enqueue ------------------------------------------------------------------


def test_enqueue_writes_one_pending_row_with_the_validated_context(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _user(pg_sessionmaker)
    assert _enqueue(pg_sessionmaker, user, key="k1") is True

    (row,) = _rows(pg_sessionmaker)
    assert row.recipient_user_id == user
    assert row.template == "booking_requested"
    assert row.status is EmailOutboxStatus.pending
    assert row.attempts == 0
    assert row.sent_at is None
    assert row.dedupe_key == "k1"
    assert row.context["booking_id"] == str(VALID["booking_requested"]["booking_id"])
    assert "email" not in row.context


def test_enqueue_refuses_an_unknown_template_or_a_bad_context(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _user(pg_sessionmaker)
    with pytest.raises(InvalidEmailContext), pg_sessionmaker.begin() as session:
        enqueue_in_session(
            session, recipient_user_id=user, template="nope", context={}, dedupe_key="x"
        )
    with pytest.raises(InvalidEmailContext), pg_sessionmaker.begin() as session:
        enqueue_in_session(
            session,
            recipient_user_id=user,
            template="booking_requested",
            context={**VALID["booking_requested"], "meeting_link": "https://meet.example/x"},
            dedupe_key="y",
        )
    assert _rows(pg_sessionmaker) == []


def test_enqueue_on_conflict_does_not_abort_caller_transaction(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A duplicate dedupe key is a no-op, so the caller's own write still commits."""
    user = _user(pg_sessionmaker)
    other = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        first = enqueue_in_session(
            session,
            recipient_user_id=user,
            template="booking_requested",
            context=VALID["booking_requested"],
            dedupe_key="same",
        )
        second = enqueue_in_session(
            session,
            recipient_user_id=user,
            template="booking_requested",
            context=VALID["booking_requested"],
            dedupe_key="same",
        )
        # The business change the notice rides on: it must still be able to write and commit.
        session.add(User(id=other, email=f"{other}@example.org", role=Role.student))
    assert (first, second) == (True, False)
    assert len(_rows(pg_sessionmaker)) == 1
    with pg_sessionmaker() as session:
        assert session.get(User, other) is not None


def test_enqueue_dedupes_against_a_row_committed_by_an_earlier_transaction(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _user(pg_sessionmaker)
    assert _enqueue(pg_sessionmaker, user, key="again") is True
    assert _enqueue(pg_sessionmaker, user, key="again") is False
    assert len(_rows(pg_sessionmaker)) == 1


def test_enqueue_rolls_back_with_the_callers_transaction(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _user(pg_sessionmaker)
    with pytest.raises(RuntimeError), pg_sessionmaker.begin() as session:
        enqueue_in_session(
            session,
            recipient_user_id=user,
            template="booking_requested",
            context=VALID["booking_requested"],
            dedupe_key="rolled-back",
        )
        raise RuntimeError("the state change failed")
    assert _rows(pg_sessionmaker) == []


def test_enqueue_skips_when_preference_off(pg_sessionmaker: sessionmaker[Session]) -> None:
    off = _user(pg_sessionmaker)
    on = _user(pg_sessionmaker)
    NotificationPreferencesService(pg_sessionmaker).set(off, booking_request=False)

    assert _enqueue(pg_sessionmaker, off, key="a") is False
    assert _enqueue(pg_sessionmaker, on, key="a2") is True
    assert [r.recipient_user_id for r in _rows(pg_sessionmaker)] == [on]


def test_the_gating_preference_is_the_one_for_the_templates_notification_type(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Template -> gating type, derived from SPEC §b.4 (inbox column paired with email column)."""
    pairs: dict[str, NotificationType] = {}
    for row in spec_b4_rows():
        inbox = [seg for seg in row[1].split(";") if "`" in seg]
        email = [seg for seg in row[3].split(";") if "`" in seg]
        if not email:
            continue
        for index, segment in enumerate(email):
            inbox_segment = inbox[index] if len(inbox) == len(email) else inbox[0]
            assert len(inbox) in {1, len(email)}, row
            type_name = re.findall(r"`([a-z_]+)`", inbox_segment)[0]
            for template in re.findall(r"`([a-z_]+)`", segment):
                pairs[template] = NotificationType(type_name)
    assert len(pairs) == 10  # non-vacuity: every template is paired
    for name, expected in pairs.items():
        assert EMAIL_TEMPLATES[name].notification_type is expected  # type: ignore[attr-defined]

    # And the gate really reads that preference: switching off the paired type blocks the template.
    for name, type_ in pairs.items():
        user = _user(pg_sessionmaker)
        NotificationPreferencesService(pg_sessionmaker).set(user, **{type_.value: False})
        assert _enqueue(pg_sessionmaker, user, key=f"gate:{name}", template=name) is False
        other = _user(pg_sessionmaker)
        assert _enqueue(pg_sessionmaker, other, key=f"gate-on:{name}", template=name) is True


# -- delivery -----------------------------------------------------------------


def test_deliver_marks_a_delivered_row_sent_after_exactly_one_attempt(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _user(pg_sessionmaker, email="tutor@example.org")
    _enqueue(pg_sessionmaker, user)
    provider = RecordingProvider()

    assert _deliver(pg_sessionmaker, provider) == 1

    (row,) = _rows(pg_sessionmaker)
    assert row.status is EmailOutboxStatus.sent
    assert row.attempts == 1
    assert row.sent_at == NOW
    assert row.last_error is None
    ((to, template, context, outbox_id),) = provider.calls
    assert (to, template) == ("tutor@example.org", "booking_requested")
    assert context == row.context
    assert outbox_id == row.id


def test_deliver_with_nothing_pending_is_a_no_op(pg_sessionmaker: sessionmaker[Session]) -> None:
    provider = RecordingProvider()
    assert _deliver(pg_sessionmaker, provider) == 0
    assert provider.calls == []


def test_deliver_handles_at_most_batch_rows_oldest_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    users = [_user(pg_sessionmaker, email=f"u{i}@example.org") for i in range(5)]
    for index, user in enumerate(users):
        _enqueue(pg_sessionmaker, user, key=f"order:{index}")
    with pg_sessionmaker.begin() as session:
        for index in range(5):
            session.execute(
                sa.update(EmailOutbox)
                .where(EmailOutbox.dedupe_key == f"order:{index}")
                .values(created_at=NOW - timedelta(hours=10 - index))
            )
    provider = RecordingProvider()

    assert _deliver(pg_sessionmaker, provider, batch=2) == 2

    assert [call[0] for call in provider.calls] == ["u0@example.org", "u1@example.org"]
    statuses = [r.status for r in _rows(pg_sessionmaker)]
    assert statuses.count(EmailOutboxStatus.pending) == 3


def test_deliver_job_claims_with_skip_locked_across_two_workers(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Worker A holds row 1's lock while sending; worker B takes row 2, not waiting or doubling."""
    first = _user(pg_sessionmaker, email="first@example.org")
    second = _user(pg_sessionmaker, email="second@example.org")
    _enqueue(pg_sessionmaker, first, key="w:1")
    _enqueue(pg_sessionmaker, second, key="w:2")
    with pg_sessionmaker.begin() as session:
        for key, hours in (("w:1", 2), ("w:2", 1)):
            session.execute(
                sa.update(EmailOutbox)
                .where(EmailOutbox.dedupe_key == key)
                .values(created_at=NOW - timedelta(hours=hours))
            )

    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    class _BlockingProvider(RecordingProvider):
        def send(
            self,
            to: str,
            template: str,
            context: Mapping[str, object],
            *,
            outbox_id: uuid.UUID | None = None,
        ) -> None:
            super().send(to, template, context, outbox_id=outbox_id)
            entered.set()
            assert release.wait(timeout=20)

    worker_a = _BlockingProvider()
    worker_b = RecordingProvider()

    def run_a() -> None:
        try:
            _deliver(pg_sessionmaker, worker_a, batch=1)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    thread = threading.Thread(target=run_a)
    thread.start()
    try:
        assert entered.wait(timeout=20)
        handled_by_b = _deliver(pg_sessionmaker, worker_b)
    finally:
        release.set()
        thread.join(timeout=30)

    assert errors == []
    assert handled_by_b == 1
    assert [call[0] for call in worker_a.calls] == ["first@example.org"]
    assert [call[0] for call in worker_b.calls] == ["second@example.org"]
    assert {r.status for r in _rows(pg_sessionmaker)} == {EmailOutboxStatus.sent}


def test_failed_row_never_retried(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Decision log row 12: a failed send is final. The error text keeps no address."""
    user = _user(pg_sessionmaker, email="parent.one@example.org")
    _enqueue(pg_sessionmaker, user, template="booking_requested")
    failing = RecordingProvider(
        fail_with=ExternalServiceError(
            "Email delivery to parent.one@example.org was rejected (HTTP 422): bad"
        )
    )

    assert _deliver(pg_sessionmaker, failing) == 1
    (row,) = _rows(pg_sessionmaker)
    assert row.status is EmailOutboxStatus.failed
    assert row.attempts == 1
    assert row.sent_at is None
    assert row.last_error is not None
    assert "@" not in row.last_error
    assert "HTTP 422" in row.last_error

    healthy = RecordingProvider()
    assert _deliver(pg_sessionmaker, healthy) == 0
    assert _deliver(pg_sessionmaker, healthy, now=NOW + timedelta(days=3)) == 0
    assert healthy.calls == []
    (again,) = _rows(pg_sessionmaker)
    assert (again.status, again.attempts) == (EmailOutboxStatus.failed, 1)


def test_an_unexpected_provider_exception_also_fails_the_row_once(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _user(pg_sessionmaker, email="x.y@example.org")
    _enqueue(pg_sessionmaker, user)
    provider = RecordingProvider(fail_with=RuntimeError("socket closed talking to x.y@example.org"))

    assert _deliver(pg_sessionmaker, provider) == 1

    (row,) = _rows(pg_sessionmaker)
    assert row.status is EmailOutboxStatus.failed
    assert row.last_error is not None
    assert "@" not in row.last_error


def test_a_stored_context_that_no_longer_validates_fails_without_sending(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _user(pg_sessionmaker)
    _enqueue(pg_sessionmaker, user)
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(EmailOutbox).values(context={"booking_id": "x", "meeting_link": "https://x"})
        )
    provider = RecordingProvider()

    assert _deliver(pg_sessionmaker, provider) == 1

    (row,) = _rows(pg_sessionmaker)
    assert provider.calls == []
    assert (row.status, row.last_error) == (EmailOutboxStatus.failed, "invalid_context")


def test_daily_cap_skips_beyond_cap(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Cap 3 over a rolling 24 h: two earlier sends count (one 23 h old), one 25 h old does not."""
    users = [_user(pg_sessionmaker, email=f"c{i}@example.org") for i in range(6)]
    for index, user in enumerate(users):
        _enqueue(pg_sessionmaker, user, key=f"cap:{index}")
    sender = _user(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        for hours, key in ((1, "old:1"), (23, "old:23"), (25, "old:25")):
            session.add(
                EmailOutbox(
                    recipient_user_id=sender,
                    template="booking_requested",
                    context=VALID["booking_requested"],
                    dedupe_key=key,
                    status=EmailOutboxStatus.sent,
                    attempts=1,
                    sent_at=NOW - timedelta(hours=hours),
                )
            )
    provider = RecordingProvider()

    assert _deliver(pg_sessionmaker, provider, cap=3) == 6

    with pg_sessionmaker() as session:
        pending_keys = [f"cap:{i}" for i in range(6)]
        rows = list(
            session.scalars(sa.select(EmailOutbox).where(EmailOutbox.dedupe_key.in_(pending_keys)))
        )
    by_status = {s: [r for r in rows if r.status is s] for s in EmailOutboxStatus}
    assert len(by_status[EmailOutboxStatus.sent]) == 1  # 2 counted earlier + 1 = cap
    assert len(by_status[EmailOutboxStatus.skipped]) == 5
    assert {r.last_error for r in by_status[EmailOutboxStatus.skipped]} == {"daily_cap"}
    assert all(r.sent_at is None and r.attempts == 1 for r in by_status[EmailOutboxStatus.skipped])
    assert len(provider.calls) == 1


def test_a_zero_cap_sends_nothing(pg_sessionmaker: sessionmaker[Session]) -> None:
    _enqueue(pg_sessionmaker, _user(pg_sessionmaker))
    provider = RecordingProvider()
    assert _deliver(pg_sessionmaker, provider, cap=0) == 1
    assert provider.calls == []
    (row,) = _rows(pg_sessionmaker)
    assert (row.status, row.last_error) == (EmailOutboxStatus.skipped, "daily_cap")
