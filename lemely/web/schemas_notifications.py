"""``/api/notifications`` DTOs (P5.6 chunk C).

The inbox is **role-agnostic** — a student, a teacher and a parent each have
one, and the five :class:`~lemely.db.models.enums.NotificationType` values
already span all three audiences. So these DTOs carry no role, no class and no
school: a notification is addressed to a *user*, and every route reads the
token's ``sub``.

**Structurally answer-only, same guarantee P5.3 and P5.5 established.** No
field shaped like a mark, grade or percentage exists on any model here, and
``tests/`` introspects the field sets, so a well-meaning future addition fails
a test instead of reaching the wire. ``payload`` is the one free-form field and
it is documented — and tested — as carrying **identifiers only**: D5.9 §2's
"a notification is a pointer, never the data" is what makes suppressing a row
lossless, and a payload holding a mark would quietly stop that being true.

The push-subscription request body deliberately mirrors the **browser's own**
``PushSubscription.toJSON()`` shape (``endpoint`` plus a nested ``keys``
object), so a client passes the subscription straight through rather than
unpacking and re-packing it. A shape of our own invention would be one more
place for a key to be mis-copied, and this one is fixed by the Push API.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic needs the real type at runtime
from typing import Annotated

from pydantic import Field

from lemely.web.schemas import ApiModel


class NotificationDTO(ApiModel):
    """One inbox row as its recipient sees it (G-12)."""

    notificationId: str
    type: str
    """One of the five :class:`~lemely.db.models.enums.NotificationType`
    values, sent as its string name so a client can route on it without
    parsing the title."""
    title: str
    body: str | None
    payload: dict[str, str]
    """Identifiers the screen needs to link somewhere — an upload id, an
    announcement id, a class id.

    Typed as ``dict[str, str]`` rather than an unconstrained JSON object on
    purpose: the column is JSONB and would happily hold a number, and the
    first number anyone put in it would be a mark. Restricting the wire type
    to strings makes "a payload is a pointer" (D5.9 §2) a property of the
    contract rather than a convention every future seam has to remember."""
    createdAt: datetime
    readAt: datetime | None
    """When the recipient first opened it; ``None`` means unread. Re-marking
    does not move it — first-read time is the useful number."""


class NotificationsPageDTO(ApiModel):
    """A page of the caller's inbox, newest first."""

    notifications: list[NotificationDTO]


class NotificationCountsDTO(ApiModel):
    """Badge numbers for the caller's inbox."""

    unread: int
    total: int
    unreadByType: dict[str, int]
    """Unread counts keyed by type name. Types with no unread rows are absent
    rather than present-as-zero, so a client renders what it is given."""


class NotificationReadReceiptDTO(ApiModel):
    """The result of marking one notification read."""

    notificationId: str
    readAt: datetime


class MarkAllReadDTO(ApiModel):
    """The result of clearing the inbox."""

    markedRead: int
    """How many rows actually changed. A second call returns 0 — it is
    idempotent, not a no-op that lies about having done work."""


class PushSubscriptionKeysDTO(ApiModel):
    """The browser's public key material, exactly as the Push API names it."""

    p256dh: Annotated[str, Field(min_length=1, max_length=255)]
    auth: Annotated[str, Field(min_length=1, max_length=255)]


class PushSubscribeRequestDTO(ApiModel):
    """A browser's ``PushSubscription.toJSON()``, passed through unchanged."""

    endpoint: Annotated[str, Field(min_length=1, max_length=2048)]
    keys: PushSubscriptionKeysDTO


class PushSubscriptionDTO(ApiModel):
    """One stored subscription, acknowledged back to the browser that sent it.

    Carries no key material. The browser already holds its own keys and has no
    use for anyone else's, so echoing them back would widen the blast radius
    of any future logging or caching mistake for no gain.
    """

    endpoint: str
    createdAt: datetime


class PushUnsubscribeRequestDTO(ApiModel):
    """The endpoint to forget. Scoped to the caller by the service."""

    endpoint: Annotated[str, Field(min_length=1, max_length=2048)]


class PushUnsubscribeResultDTO(ApiModel):
    """Whether a subscription was removed."""

    removed: bool


class PushConfigDTO(ApiModel):
    """What a client needs to subscribe — or the honest reason it cannot.

    ``available`` is a **tri-state honesty** field in the sense D4.10/D5.8
    established: this build ships with no VAPID keys, so the answer is
    "configured and here is the key" or "not configured", never a fabricated
    key or a 500. A client seeing ``available: false`` hides the enable-push
    control rather than offering one that cannot work.
    """

    available: bool
    publicKey: str | None
    """The application server's base64url public key, for
    ``pushManager.subscribe``. Public by definition — it is handed to every
    browser that subscribes — so it is not a secret leaking through an API."""


__all__ = [
    "MarkAllReadDTO",
    "NotificationCountsDTO",
    "NotificationDTO",
    "NotificationReadReceiptDTO",
    "NotificationsPageDTO",
    "PushConfigDTO",
    "PushSubscribeRequestDTO",
    "PushSubscriptionDTO",
    "PushSubscriptionKeysDTO",
    "PushUnsubscribeRequestDTO",
    "PushUnsubscribeResultDTO",
]
