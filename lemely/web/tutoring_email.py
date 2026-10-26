"""The sweeper job that delivers ``email_outbox`` rows, and the mock-mode reporting (SPEC §b.4).

There is no request-time send and no ``BackgroundTask``: on Cloud Run, CPU is throttled outside
requests, so post-response work may never run. Delivery is instead one more job on the existing
60-second sweeper (:class:`~lemely.web.scheduled_notifications.Sweeper`), which only runs it when
it was built with an email provider.

Per tick, at most ``batch`` rows are handled, **each in its own transaction**:

1. ``SELECT ... WHERE status = 'pending' ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED``
   (safe across replicas);
2. decide: a placeholder address or an unverified recipient is ``skipped``; the mock provider is
   ``skipped`` with ``last_error='mock_provider'`` and never ``sent`` (SC-6); a 24 h sent count at
   or above ``[tutoring] email_daily_cap`` is ``skipped``;
3. send, and mark ``sent`` or ``failed`` with ``attempts = 1``.

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
    mark_in_session,
    recipient_in_session,
)
from lemely.db.models.enums import EmailOutboxStatus
from lemely.io.notify_email import InvalidEmailContext, scrub_error, validate_context

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

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
    """Claim and finish one row in the caller's transaction. ``None`` when nothing is pending."""
    row = claim_next_pending_in_session(session)
    if row is None:
        return None

    def finish(status: EmailOutboxStatus, error: str | None = None) -> EmailOutboxStatus:
        mark_in_session(
            session,
            row.id,
            status=status,
            last_error=error,
            sent_at=moment if status is EmailOutboxStatus.sent else None,
        )
        return status

    recipient = recipient_in_session(session, row.recipient_user_id)
    if recipient is None:
        return finish(EmailOutboxStatus.skipped, "recipient_missing")
    address = recipient.email
    if address.lower().endswith(PLACEHOLDER_EMAIL_DOMAIN):
        return finish(EmailOutboxStatus.skipped, "placeholder_address")
    if not recipient.email_verified:
        return finish(EmailOutboxStatus.skipped, "unverified_recipient")

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
