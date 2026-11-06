"""The transactional email outbox (SPEC §b.4, §a.2 ``email_outbox``).

Two halves, both session-scoped so the caller owns the transaction:

* **Writing** (:func:`enqueue_in_session`) happens inside the business change's transaction, so
  the mail commits or rolls back with it. The insert is ``ON CONFLICT (dedupe_key) DO NOTHING``:
  a duplicate is a quiet ``False``, never an error that would abort the caller (F17). A
  recipient who switched the matching notification type off gets no row at all.
* **Delivery** (:func:`claim_next_pending_in_session` and friends) is used by the sweeper job
  in :mod:`lemely.web.tutoring_email`: one row at a time under ``FOR UPDATE SKIP LOCKED``.

The outbox never stores an address (F18, EM-5): the recipient is a user id, and the address is
read from ``users`` at send time by :func:`recipient_in_session`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.db.models.enums import EmailOutboxStatus
from lemely.db.models.ops import NotificationPreference
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.users import User
from lemely.db.notification_prefs_repo import DEFAULTS
from lemely.db.notification_repo import PREFERENCE_FIELD_FOR_TYPE
from lemely.io.notify_email import EMAIL_TEMPLATES, validate_context

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping
    from datetime import datetime

    from sqlalchemy.orm import Session

#: Domain of the address synthesised for a phone-only parent. Mirrors
#: ``lemely.db.parent_repo._PLACEHOLDER_EMAIL_DOMAIN`` (pinned equal by
#: ``tests/test_tutoring_email.py``); such an address is never mailed (EM-6).
PLACEHOLDER_EMAIL_DOMAIN: Final = "@parents.lemely.local"

#: Key of the transaction-scoped advisory lock that serialises the daily-cap count with the send
#: it guards (SC-15). One fixed key for this job; the value only has to be stable and unlikely to
#: collide with another advisory-lock user (ASCII "LEMELY" followed by 1).
EMAIL_CAP_LOCK_KEY: Final = 0x4C454D454C59_0001

#: ``email_outbox.dedupe_key`` is varchar(200).
DEDUPE_KEY_MAX: Final = 200


@dataclass(frozen=True, slots=True)
class OutboxRow:
    """A claimed pending row, detached from the session."""

    id: uuid.UUID
    recipient_user_id: uuid.UUID
    template: str
    context: dict[str, object]


@dataclass(frozen=True, slots=True)
class Recipient:
    """What the delivery job needs to know about the user a row is addressed to."""

    email: str
    email_verified: bool


def _preference_is_on(session: Session, user_id: uuid.UUID, field: str) -> bool:
    """Read ``field`` from the user's stored preferences, or the documented default.

    A direct read in the caller's session: :class:`NotificationPreferencesService` opens its
    own session, which would not share the caller's transaction or connection.
    """
    row = session.get(NotificationPreference, user_id)
    if row is None:
        return bool(getattr(DEFAULTS, field))
    return bool(getattr(row, field))


def template_enabled_in_session(session: Session, user_id: uuid.UUID, template: str) -> bool:
    """Whether ``user_id`` still has the notification type that gates ``template`` switched on.

    Used twice: when a row is written, and again at send time, because a preference changed in
    between must stop the mail (R2).
    """
    field = PREFERENCE_FIELD_FOR_TYPE[EMAIL_TEMPLATES[template].notification_type]
    return _preference_is_on(session, user_id, field)


def lock_daily_cap_in_session(session: Session) -> None:
    """Take the transaction-scoped advisory lock that serialises the cap count with the send.

    Without it two replicas could both count 59 of 60 and both send. The lock is released when the
    caller's transaction ends, after the row is marked ``sent`` and so counted.
    """
    session.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": EMAIL_CAP_LOCK_KEY})


def enqueue_in_session(
    session: Session,
    *,
    recipient_user_id: uuid.UUID,
    template: str,
    context: Mapping[str, object],
    dedupe_key: str,
) -> bool:
    """Queue one email in the caller's transaction. ``True`` when a row was written.

    ``False`` means the recipient has the matching notification type switched off, or a row with
    this ``dedupe_key`` already exists. Neither raises, and neither poisons the transaction.

    Raises:
        InvalidEmailContext: the template is unknown or ``context`` fails its schema.
        ValueError: ``dedupe_key`` is empty or longer than the column.
    """
    stored = validate_context(template, context)
    if not 1 <= len(dedupe_key) <= DEDUPE_KEY_MAX:
        raise ValueError("dedupe_key must be 1 to 200 characters")
    if not template_enabled_in_session(session, recipient_user_id, template):
        return False
    statement = (
        pg_insert(EmailOutbox)
        .values(
            recipient_user_id=recipient_user_id,
            template=template,
            context=stored,
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(index_elements=[EmailOutbox.dedupe_key])
        .returning(EmailOutbox.id)
    )
    return session.execute(statement).scalar_one_or_none() is not None


def claim_next_pending_in_session(session: Session) -> OutboxRow | None:
    """Lock and return the oldest pending row not already locked by another worker.

    ``ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED``: two replicas never take the same
    row and never wait on each other. The lock lasts until the caller's transaction ends.
    """
    model = session.execute(
        sa.select(EmailOutbox)
        .where(EmailOutbox.status == EmailOutboxStatus.pending)
        .order_by(EmailOutbox.created_at, EmailOutbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if model is None:
        return None
    return OutboxRow(
        id=model.id,
        recipient_user_id=model.recipient_user_id,
        template=model.template,
        context=dict(model.context),
    )


def recipient_in_session(session: Session, user_id: uuid.UUID) -> Recipient | None:
    """The address and verification state of ``user_id``, or ``None`` if the user is gone."""
    row = session.execute(
        sa.select(User.email, User.email_verified_at).where(User.id == user_id)
    ).one_or_none()
    if row is None:
        return None
    return Recipient(email=row.email, email_verified=row.email_verified_at is not None)


def count_sent_since_in_session(session: Session, since: datetime) -> int:
    """How many rows were marked ``sent`` at or after ``since`` (the daily-cap count)."""
    count = session.scalar(
        sa.select(sa.func.count())
        .select_from(EmailOutbox)
        .where(EmailOutbox.status == EmailOutboxStatus.sent, EmailOutbox.sent_at >= since)
    )
    return int(count or 0)


def mark_in_session(
    session: Session,
    outbox_id: uuid.UUID,
    *,
    status: EmailOutboxStatus,
    last_error: str | None,
    sent_at: datetime | None,
) -> None:
    """Record the row's final outcome.

    ``attempts`` counts send attempts: 1 for ``sent`` and ``failed``, 0 for ``skipped``, because a
    row that was never handed to the provider was not attempted. Never more than 1 (row 12).
    """
    session.execute(
        sa.update(EmailOutbox)
        .where(EmailOutbox.id == outbox_id)
        .values(
            status=status,
            attempts=0 if status is EmailOutboxStatus.skipped else 1,
            last_error=last_error,
            sent_at=sent_at,
            updated_at=sa.func.now(),
        )
    )


__all__ = [
    "DEDUPE_KEY_MAX",
    "EMAIL_CAP_LOCK_KEY",
    "PLACEHOLDER_EMAIL_DOMAIN",
    "OutboxRow",
    "Recipient",
    "claim_next_pending_in_session",
    "count_sent_since_in_session",
    "enqueue_in_session",
    "lock_daily_cap_in_session",
    "mark_in_session",
    "recipient_in_session",
    "template_enabled_in_session",
]
