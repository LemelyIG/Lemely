"""The notification inbox and push-subscription endpoints (``/api/notifications``, P5.6 chunk C).

**Role-agnostic on purpose.** Every other Phase-5 router this mirrors
(:mod:`~lemely.web.routers.leaderboard`, :mod:`~lemely.web.routers.friends`,
:mod:`~lemely.web.routers.student_announcements`) is student-only, but the five
:class:`~lemely.db.models.enums.NotificationType` values already span three
audiences — ``at_risk_alert`` goes to a teacher and to a parent, and both need
somewhere to read it. Gating this router on ``Role.student`` would have built
an inbox that two of its three intended readers cannot open.

Identity is **structurally** the token's ``sub`` on every route. No route takes
a user id, so one user cannot read, clear or unsubscribe another's inbox by
crafting a request — the same property that made P5.4 chunk B and P5.5 chunk B
safe, and the reason none of these handlers contains an ownership check to get
wrong. ``mark_read`` puts the recipient in its UPDATE's WHERE clause, so
another user's notification id is indistinguishable from a nonexistent one and
this router returns one 404 for both (no existence oracle, P5.3's rule).

The push endpoints do not send anything; they only record where a push *could*
go. Sending is :mod:`lemely.web.notify`'s, fail-open, at the seams that
actually produce a notification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lemely.db.notification_repo import DEFAULT_INBOX_LIMIT, NotificationService
from lemely.runtime.config import Settings  # noqa: TC001 - FastAPI resolves this at runtime
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_notification_service,
    get_push_transport,
    get_settings,
)
from lemely.web.push import NotificationTransport  # noqa: TC001 - FastAPI resolves this at runtime
from lemely.web.schemas_notifications import (
    MarkAllReadDTO,
    NotificationCountsDTO,
    NotificationDTO,
    NotificationReadReceiptDTO,
    NotificationsPageDTO,
    PushConfigDTO,
    PushSubscribeRequestDTO,
    PushSubscriptionDTO,
    PushUnsubscribeRequestDTO,
    PushUnsubscribeResultDTO,
)

if TYPE_CHECKING:
    from lemely.db.notification_repo import NotificationRow

# ``Settings`` and ``NotificationTransport`` are imported at runtime, not under
# TYPE_CHECKING: FastAPI resolves every ``Annotated[...]`` parameter annotation
# through pydantic at import time, and with ``from __future__ import
# annotations`` a name that only exists for the type checker leaves it with an
# unresolvable ForwardRef — the route then raises PydanticUserError on its
# first request rather than failing at import, which is a much later and much
# more confusing place to find out.

router = APIRouter(prefix="/api/notifications")


def _to_dto(row: NotificationRow) -> NotificationDTO:
    """Render one inbox row, flattening its payload to strings.

    The column is JSONB and can hold anything; the wire contract is
    ``dict[str, str]`` so that "a payload is a pointer, never the data"
    (D5.9 §2) is enforced by the contract rather than remembered by each seam.
    Coercing here rather than validating strictly is deliberate: a row written
    by some future seam with an integer id must still be *readable*, and a
    whole inbox that 500s because one row holds a number is a worse failure
    than a stringified id.
    """
    return NotificationDTO(
        notificationId=str(row.id),
        type=row.type.value,
        title=row.title,
        body=row.body,
        payload={key: str(value) for key, value in row.payload.items()},
        createdAt=row.created_at,
        readAt=row.read_at,
    )


@router.get("", response_model=NotificationsPageDTO)
def list_notifications(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    unreadOnly: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = DEFAULT_INBOX_LIMIT,
) -> NotificationsPageDTO:
    """G-12: the caller's notifications, newest first.

    An empty list is a **successful** response and an honest one — a user
    nothing has happened to yet has an empty inbox, which is not an error and
    not a 404.
    """
    rows = service.list_for_user(auth.user_id, unread_only=unreadOnly, limit=limit)
    return NotificationsPageDTO(notifications=[_to_dto(row) for row in rows])


@router.get("/counts", response_model=NotificationCountsDTO)
def notification_counts(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationCountsDTO:
    """Badge numbers over the caller's whole inbox.

    Separate from :func:`list_notifications` because that one is ``LIMIT``-ed:
    a badge derived from the page length would stop counting at the page size
    and quietly under-report, the same trap P5.5's unread-count route exists
    to avoid.
    """
    counts = service.counts(auth.user_id)
    return NotificationCountsDTO(
        unread=counts.unread,
        total=counts.total,
        unreadByType={type.value: count for type, count in counts.by_type.items()},
    )


@router.post("/{notification_id}/read", response_model=NotificationReadReceiptDTO)
def mark_notification_read(
    notification_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationReadReceiptDTO:
    """Mark one notification read. Idempotent; 200 on the second call too.

    Raises:
        HTTPException: 404 when the notification does not exist **or** is not
            the caller's — deliberately one response for both, so nobody can
            probe for the existence of another user's notification ids. 422
            for a malformed ``notification_id``.
    """
    try:
        row = service.mark_read(auth.user_id, notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None or row.read_at is None:
        raise HTTPException(status_code=404, detail="Notification not found")

    # Echo the canonical id, not the raw path string: ``uuid.UUID`` accepts
    # uppercase hex, braces and a ``urn:uuid:`` prefix, so returning the input
    # verbatim hands back an id that never matches the one in the list
    # response — P5.4 chunk B's defect, then P5.5 chunk B's, now not repeated.
    return NotificationReadReceiptDTO(notificationId=str(row.id), readAt=row.read_at)


@router.post("/read-all", response_model=MarkAllReadDTO)
def mark_all_notifications_read(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> MarkAllReadDTO:
    """Clear the caller's inbox. Returns how many rows actually changed."""
    return MarkAllReadDTO(markedRead=service.mark_all_read(auth.user_id))


@router.get("/push/config", response_model=PushConfigDTO)
def push_config(
    _auth: Annotated[AuthContext, Depends(get_auth_context)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PushConfigDTO:
    """What the browser needs to call ``pushManager.subscribe`` — or an honest no.

    This build has no VAPID keys, so the usual answer here is
    ``available: false`` with a null key. That is a supported state, not a
    failure (D5.9 §4): a client hides the enable-push control instead of
    offering one that cannot work, and nothing about the inbox stops working.
    """
    return PushConfigDTO(
        available=transport.available,
        # Only ever published alongside ``available: true``. With a partial
        # configuration the transport is unavailable, and shipping the key
        # anyway would invite a client to subscribe against a server that
        # cannot sign a push.
        publicKey=settings.push.vapid_public_key if transport.available else None,
    )


@router.post("/push/subscribe", response_model=PushSubscriptionDTO)
def subscribe_to_push(
    body: PushSubscribeRequestDTO,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> PushSubscriptionDTO:
    """Record where this browser can be pushed to. Idempotent per endpoint.

    Accepted **even when no VAPID keys are configured.** A subscription is a
    durable fact about a browser, and refusing to store it on an unconfigured
    server would mean every user had to re-subscribe the day keys were added.
    The transport's availability governs sending, not recording.

    Re-subscribing an endpoint that belongs to a different user **moves** it
    (the service's call, migration 0018's unique index): the endpoint
    identifies a browser install, not a person, so two users sharing a browser
    produce the same endpoint and leaving the first row would push the first
    user's notifications to the second. That is a privacy defect, not a
    duplicate row.
    """
    row = service.subscribe(
        auth.user_id,
        body.endpoint,
        body.keys.p256dh,
        body.keys.auth,
    )
    return PushSubscriptionDTO(endpoint=row.endpoint, createdAt=row.created_at)


@router.post("/push/unsubscribe", response_model=PushUnsubscribeResultDTO)
def unsubscribe_from_push(
    body: PushUnsubscribeRequestDTO,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> PushUnsubscribeResultDTO:
    """Forget one of the caller's push endpoints.

    ``removed: false`` for an endpoint that was never the caller's is a
    **success**, not a 404: the postcondition the client asked for ("this
    browser no longer receives my pushes") holds either way, and answering 404
    would tell a caller whether some endpoint string belongs to somebody else.

    A POST rather than a DELETE because the endpoint is a 2048-character URL
    and belongs in a body, not a path segment or a query string that lands in
    every access log.
    """
    return PushUnsubscribeResultDTO(removed=service.unsubscribe(auth.user_id, body.endpoint))


__all__ = ["router"]
