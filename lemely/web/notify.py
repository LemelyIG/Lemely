"""Router-layer helper that notifies a user without ever failing the underlying action.

The exact shape of :mod:`lemely.web.xp_awards`, for the same reason. Every
seam that produces a notification does so *after* the thing being announced has
already committed — the paper is marked, the announcement is written, the
at-risk assessment has been made. D5.9 §1 is binding: a push service being
unreachable, or a bug in the inbox write, must never turn an already-successful
action into an error response.

:func:`notify_safely` is the **single** place ``lemely.web`` calls
:meth:`~lemely.db.notification_repo.NotificationService.create` from, so the
three seams cannot drift into three slightly different ``try``/``except``
blocks. It is not silent: a failure is logged at exception level with the seam
name and the recipient id — never a mark, a grade or a notification body.

**What it does, in order, and why the order matters:**

1. Write the inbox row. That row *is* the notification (D5.9 §1); everything
   after this point is delivery.
2. Stop if the row was not written. A type toggled off means the user asked
   not to be told (D5.9 §2), and a duplicate means they already were.
3. Stop if quiet hours suppressed the push. The row still exists and the user
   will see it when they next open the app — quiet hours are a timing
   preference, never a content one.
4. Fan out to every stored subscription, deleting the ones a push service
   reports as permanently gone.

An outcome that is not "delivered" never propagates: :meth:`send` returns
results rather than raising, and the whole fan-out is wrapped anyway, because
a notification that reached the inbox has already done its most important job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from lemely.db.notification_repo import NotificationOutcome

if TYPE_CHECKING:
    import uuid

    from lemely.db.models.enums import NotificationType
    from lemely.db.notification_repo import NotificationRow, NotificationService
    from lemely.web.push import NotificationTransport

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NotifyResult:
    """What one :func:`notify_safely` call actually managed to do.

    ``outcome`` is ``None`` only when the inbox write itself raised — the one
    case where we genuinely do not know what happened. Every other field
    describes delivery, which is allowed to fail freely.
    """

    outcome: NotificationOutcome | None
    row: NotificationRow | None = None
    #: Why no push was attempted, when a row exists but was not pushed:
    #: ``"quiet_hours"``, ``"transport_unavailable"``, ``"no_subscriptions"``.
    push_suppressed_reason: str | None = None
    pushes_attempted: int = 0
    pushes_delivered: int = 0
    #: Endpoints a push service reported as 404/410 and that were deleted.
    subscriptions_forgotten: int = 0

    @property
    def created(self) -> bool:
        """``True`` when an inbox row was written by this call."""
        return self.outcome is NotificationOutcome.created


def notify_safely(
    service: NotificationService,
    transport: NotificationTransport,
    *,
    user_id: uuid.UUID | str,
    type: NotificationType,
    title: str,
    body: str | None = None,
    payload: dict[str, object] | None = None,
    dedupe_key: str | None = None,
    seam: str,
) -> NotifyResult:
    """Write one notification and best-effort push it. Returns; never raises.

    Args:
        service: The process-wide
            :class:`~lemely.db.notification_repo.NotificationService` (via
            :func:`~lemely.web.deps.get_notification_service`).
        transport: The push transport (via
            :func:`~lemely.web.deps.get_push_transport`). An unavailable one
            is normal, not an error (D5.9 §4).
        user_id: **The recipient**, who is frequently not the caller — a
            teacher or a parent for ``at_risk_alert``. This is the one
            parameter here that is not ``auth.user_id``, and every call site
            must derive it from a server-side relationship (an enrolment, a
            parent link), never from the request body.
        type: Which of the five
            :class:`~lemely.db.models.enums.NotificationType` values this is.
            The recipient's preference for it is what decides whether a row is
            written at all, and for a parent alert that is the *parent's*
            preference (D5.9 §3).
        title: The headline. A pointer, not the data — never a mark or grade.
        body: Optional supporting line, under the same rule.
        payload: Identifiers the screen needs to link somewhere. Values should
            be strings; the wire contract coerces them and D5.9 §2's "a
            notification is a pointer" is what makes row suppression lossless.
        dedupe_key: Idempotency key, or ``None`` for the types with no natural
            one. ``grade_ready`` keys on the **upload**, never the attempt —
            ``persist_correction`` mints a fresh ``Attempt`` on every run, so
            an attempt-keyed notification re-fires on every re-correction of
            one PDF (D5.9 §6, written down before it could recur as D5.3 did).
        seam: A short stable label for which call site this is, used only in
            the log line so a failure can be traced back.

    Returns:
        A :class:`NotifyResult`. ``outcome is None`` means the inbox write
        raised and was swallowed; callers must treat it exactly like any other
        "no notification happened" outcome, because the action they just
        performed has already succeeded and stays succeeded.
    """
    try:
        result = service.create(
            user_id,
            type,
            title,
            body=body,
            payload=payload,
            dedupe_key=dedupe_key,
        )
    except Exception:
        log.exception("notification_create_failed", seam=seam, user_id=str(user_id))
        return NotifyResult(outcome=None)

    if result.row is None:
        # Opted out, or a duplicate. Both are successes with nothing to push:
        # the user either asked not to hear this, or already has.
        return NotifyResult(
            outcome=result.outcome,
            push_suppressed_reason=result.push_suppressed_reason,
        )
    if not result.push_allowed:
        # Quiet hours. The row is written and stays written (D5.9 §2) — the
        # student sees it when they next open the app, they just are not woken
        # up for it.
        return NotifyResult(
            outcome=result.outcome,
            row=result.row,
            push_suppressed_reason=result.push_suppressed_reason,
        )
    if not transport.available:
        return NotifyResult(
            outcome=result.outcome,
            row=result.row,
            push_suppressed_reason="transport_unavailable",
        )

    try:
        return _push_to_every_device(service, transport, user_id=user_id, result_row=result.row)
    except Exception:
        # The row is already written, which is the part that matters. A
        # failure here loses a buzz, not a notification.
        log.exception("notification_push_failed", seam=seam, user_id=str(user_id))
        return NotifyResult(
            outcome=NotificationOutcome.created,
            row=result.row,
            push_suppressed_reason="push_failed",
        )


def _push_to_every_device(
    service: NotificationService,
    transport: NotificationTransport,
    *,
    user_id: uuid.UUID | str,
    result_row: NotificationRow,
) -> NotifyResult:
    """Send to each of a user's subscriptions, forgetting the dead ones."""
    subscriptions = service.subscriptions_for(user_id)
    if not subscriptions:
        return NotifyResult(
            outcome=NotificationOutcome.created,
            row=result_row,
            push_suppressed_reason="no_subscriptions",
        )

    delivered = 0
    forgotten = 0
    for subscription in subscriptions:
        outcome = transport.send(subscription)
        if outcome.delivered:
            delivered += 1
        elif outcome.should_forget:
            # 404/410: this browser subscription is permanently gone (D5.9 §4).
            # Deleting it here — rather than retrying forever — is what stops
            # the table filling with endpoints that can never succeed. Other
            # failures (a 503, a timeout) leave the row alone: one bad minute
            # at a push service must not evict a healthy device.
            forgotten += 1 if service.forget_endpoint(subscription.endpoint) else 0

    return NotifyResult(
        outcome=NotificationOutcome.created,
        row=result_row,
        pushes_attempted=len(subscriptions),
        pushes_delivered=delivered,
        subscriptions_forgotten=forgotten,
    )


__all__ = ["NotifyResult", "notify_safely"]
