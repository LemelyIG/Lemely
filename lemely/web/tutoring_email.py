"""The sweeper job that delivers ``email_outbox`` rows, and the mock-mode reporting (SPEC §b.4).

There is no request-time send and no ``BackgroundTask``: on Cloud Run, CPU is throttled outside
requests, so post-response work may never run. Delivery is instead one more job on the existing
60-second sweeper (:class:`~lemely.web.scheduled_notifications.Sweeper`), which only runs it when
it was built with an email provider.

Per tick, at most ``batch`` rows are handled, **each in its own transaction**:

1. ``SELECT ... WHERE status = 'pending' ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED``
   (safe across replicas);
2. decide: a template this release does not know is ``failed`` (``unknown_template``); a
   placeholder address, an unverified recipient, or a recipient who has since switched
   the template's notification type off is ``skipped``; the mock provider is
   ``skipped`` with ``last_error='mock_provider'`` and never ``sent`` (SC-6); a 24 h sent count at
   or above ``[tutoring] email_daily_cap`` is ``skipped`` (counted under an advisory lock, so
   replicas cannot overshoot);
3. send, and mark ``sent`` or ``failed`` with ``attempts = 1``. A ``skipped`` row keeps
   ``attempts = 0``: it was never handed to the provider.

Any unexpected exception while one claimed row is handled marks **that row** ``failed``
(``error:<exception class>``, no message, so no address) and the loop goes on: one bad row can
never stop the rows behind it, which include the parent link and unlink safety mails.

**First attempt only: a ``failed`` row is never retried** (decision log row 12); nothing selects
anything but ``pending``. The send happens inside the transaction, so a crash between send and
commit rolls the row back to ``pending`` and a rare duplicate is possible; a row can also stay
``pending`` while no instance is serving traffic (both documented in DELIVERY §5.7).
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Literal

import structlog

from lemely.db.email_outbox_repo import (
    PLACEHOLDER_EMAIL_DOMAIN,
    claim_next_pending_in_session,
    count_sent_since_in_session,
    lock_daily_cap_in_session,
    mark_in_session,
    recipient_in_session,
    template_enabled_in_session,
)
from lemely.db.models.enums import EmailOutboxStatus
from lemely.io.notify_email import (
    EMAIL_TEMPLATES,
    InvalidEmailContext,
    scrub_error,
    validate_context,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.email_outbox_repo import OutboxRow
    from lemely.io.notify_email import TransactionalEmailProvider
    from lemely.runtime.config import Settings

log = structlog.get_logger(__name__)

MOCK_WARNING: Final = (
    "Tutoring email delivery is in mock mode: no email will be sent, and queued mails are "
    "recorded as skipped. Set [email] api_key (LEMELY_EMAIL__API_KEY) to deliver them."
)

#: The rolling window the daily cap counts over.
CAP_WINDOW: Final = timedelta(hours=24)


def email_delivery_mode(settings: Settings) -> Literal["provider", "mock"]:
    """``"mock"`` exactly when ``[email] api_key`` is unset, the condition that selects the mock."""
    return "mock" if settings.email.api_key is None else "provider"


def doctor_lines(settings: Settings) -> list[str]:
    """The lines ``lemely doctor`` prints for tutoring email. Never includes the key."""
    if email_delivery_mode(settings) == "mock":
        return [f"WARNING: {MOCK_WARNING}"]
    return [
        "Tutoring email delivery: provider configured "
        f"(daily cap {settings.tutoring.email_daily_cap})"
    ]


def _deliver_one(
    session: Session,
    *,
    provider: TransactionalEmailProvider,
    daily_cap: int,
    moment: datetime,
) -> EmailOutboxStatus | None:
    """Claim and finish one row in the caller's transaction. ``None`` when nothing is pending.

    Whatever goes wrong while the claimed row is decided and sent is that row's failure, never
    the job's: the work runs in a savepoint, so after an unexpected exception (a database error
    included) the savepoint is rolled back and the row, still locked, is marked ``failed`` with
    ``last_error='error:<exception class>'``. The class name only, because the message may carry
    the address. Without this, the oldest bad row would be claimed first on every tick and block
    every row behind it. Only a failure to claim or to mark propagates.
    """
    row = claim_next_pending_in_session(session)
    if row is None:
        return None
    try:
        with session.begin_nested():
            return _decide_and_send(
                session, row, provider=provider, daily_cap=daily_cap, moment=moment
            )
    except Exception as exc:
        reason = f"error:{type(exc).__name__}"
        log.warning("tutoring_email_row_failed", outbox_id=str(row.id), reason=reason)
        mark_in_session(
            session, row.id, status=EmailOutboxStatus.failed, last_error=reason, sent_at=None
        )
        return EmailOutboxStatus.failed


def _decide_and_send(
    session: Session,
    row: OutboxRow,
    *,
    provider: TransactionalEmailProvider,
    daily_cap: int,
    moment: datetime,
) -> EmailOutboxStatus:
    """Decide the claimed ``row``'s outcome, send it if it is due, and mark it."""

    def finish(status: EmailOutboxStatus, error: str | None = None) -> EmailOutboxStatus:
        mark_in_session(
            session,
            row.id,
            status=status,
            last_error=error,
            sent_at=moment if status is EmailOutboxStatus.sent else None,
        )
        return status

    if EMAIL_TEMPLATES.get(row.template) is None:
        # A row a later release wrote before a rollback, or a manual insert: nothing here can
        # render it or knows which preference gates it, and it must not block the queue.
        return finish(EmailOutboxStatus.failed, "unknown_template")

    recipient = recipient_in_session(session, row.recipient_user_id)
    if recipient is None:
        return finish(EmailOutboxStatus.skipped, "recipient_missing")
    address = recipient.email
    if address.lower().endswith(PLACEHOLDER_EMAIL_DOMAIN):
        return finish(EmailOutboxStatus.skipped, "placeholder_address")
    if not recipient.email_verified:
        return finish(EmailOutboxStatus.skipped, "unverified_recipient")
    if not template_enabled_in_session(session, row.recipient_user_id, row.template):
        # Switched off since the row was written (R2): the user asked not to be told.
        return finish(EmailOutboxStatus.skipped, "preference_off")

    if not provider.delivers_out_of_band:
        # Nothing leaves the building, so say so (SC-6). The provider only logs id and template.
        try:
            provider.send(address, row.template, row.context, outbox_id=row.id)
        except Exception as exc:
            return finish(
                EmailOutboxStatus.failed,
                scrub_error(f"{type(exc).__name__}: {exc}", address=address),
            )
        return finish(EmailOutboxStatus.skipped, "mock_provider")

    # Held until this transaction ends, i.e. until the send below is marked and so counted (R3).
    lock_daily_cap_in_session(session)
    if count_sent_since_in_session(session, moment - CAP_WINDOW) >= daily_cap:
        return finish(EmailOutboxStatus.skipped, "daily_cap")
    try:
        context = validate_context(row.template, row.context)
    except InvalidEmailContext:
        return finish(EmailOutboxStatus.failed, "invalid_context")
    try:
        provider.send(address, row.template, context, outbox_id=row.id)
    except Exception as exc:
        return finish(
            EmailOutboxStatus.failed,
            scrub_error(f"{type(exc).__name__}: {exc}", address=address),
        )
    return finish(EmailOutboxStatus.sent)


def deliver_tutoring_email(
    *,
    sessionmaker: sessionmaker[Session],
    provider: TransactionalEmailProvider,
    daily_cap: int,
    now: Callable[[], datetime],
    batch: int = 20,
) -> int:
    """Deliver up to ``batch`` pending rows, one transaction each. Returns rows handled.

    "Handled" counts every terminal outcome (``sent``, ``failed``, ``skipped``). The loop ends
    early when no unlocked pending row is left.
    """
    outcomes: Counter[str] = Counter()
    for _ in range(batch):
        with sessionmaker() as session, session.begin():
            status = _deliver_one(session, provider=provider, daily_cap=daily_cap, moment=now())
        if status is None:
            break
        outcomes[status.value] += 1
    handled = sum(outcomes.values())
    if handled:
        log.info("tutoring_email_delivered", handled=handled, **outcomes)
    return handled


__all__ = [
    "CAP_WINDOW",
    "MOCK_WARNING",
    "deliver_tutoring_email",
    "doctor_lines",
    "email_delivery_mode",
]
