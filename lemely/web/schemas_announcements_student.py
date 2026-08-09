"""``/api/student/announcements`` DTOs (P5.5 chunk B).

**A separate module from :mod:`lemely.web.schemas_announcements`, deliberately.**
That one is the *teacher composer's* wire contract — a create body plus the
author's own view of what they posted. This one is the *reader's* contract, and
the two diverge on the field that matters: ``readAt`` is per-viewer and has no
meaning at all in the author view (P5.5 chunk A's
:class:`~lemely.db.announcement_repo.StudentAnnouncementRow` splits the same
seam at the service layer). Widening the teacher module to serve both would
make every future teacher-composer field automatically student-visible, which
is exactly the kind of accident this split prevents.

**Structurally read-only and answer-only.** A student can do exactly two things
to an announcement — list it and mark it read — so there is no create/update
body here at all, and no field shaped like a mark, grade or percentage exists
on any of these models (D5.1 §0, MISSION §3). ``tests/`` introspects the field
sets, so an addition fails a test rather than silently reaching the wire.

Mirrors :mod:`lemely.web.schemas_friends`/:mod:`lemely.web.schemas_leaderboard`
in style: an explicit ``ApiModel`` subclass per DTO, camelCase names declared
directly, no alias generator.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic needs the real type at runtime
from typing import Literal

from lemely.web.schemas import ApiModel


class StudentAnnouncementDTO(ApiModel):
    """One announcement as the student who may read it sees it (S-28)."""

    announcementId: str
    scope: Literal["class", "school"]
    """Which audience carried this row to the reader.

    Derived from which of ``class_id``/``school_id`` is set, so the screen can
    label a whole-school notice differently from a class one without having to
    infer it from a null. The two are mutually exclusive by construction —
    :meth:`~lemely.db.announcement_repo.AnnouncementService.create` writes
    either one class row or one school-wide row, never a hybrid."""
    classId: str | None
    schoolId: str | None
    title: str
    body: str
    publishedAt: datetime
    """The **effective** publication time: ``publish_at`` when the author
    scheduled one, otherwise ``created_at``.

    Only one time field is exposed, and this is it, because it is also the key
    ``list_for_student`` orders by. Shipping the raw ``created_at`` alongside it
    would let a screen sort by the author's typing time and silently disagree
    with the server's ordering — a back-dated post would jump to the top of the
    list purely because it was written last."""
    readAt: datetime | None
    """When this student first opened it; ``None`` means unread.

    Unread is an **absence** of a receipt row, never a flag (migration
    ``0016``), and this field preserves that: there is no ``isRead`` boolean to
    drift out of step with the timestamp."""
    authorId: str
    """Opaque id of the teacher or school admin who posted it.

    A display *name* is deliberately not resolved here. Doing so is a service-
    layer query, not router wiring, and the leaderboard's D5.5 lesson makes the
    obvious shortcut dangerous: the codebase-wide ``display_name or email``
    fallback would broadcast a member of staff's contact address to every
    student in the school. When S-28 needs a name it gets one from the service,
    with no email fallback."""


class StudentAnnouncementsPageDTO(ApiModel):
    """``GET /api/student/announcements`` response."""

    announcements: list[StudentAnnouncementDTO]


class UnreadAnnouncementCountDTO(ApiModel):
    """``GET /api/student/announcements/unread-count`` response.

    Its own endpoint rather than a field on the page above: the navigation
    badge needs the number on every screen, and it must be the **true** count,
    not the length of a ``LIMIT``-ed page (see
    :meth:`~lemely.db.announcement_repo.AnnouncementService.unread_count_for_student`).
    """

    unreadCount: int


class AnnouncementReadReceiptDTO(ApiModel):
    """``POST /api/student/announcements/{announcement_id}/read`` response."""

    announcementId: str
    readAt: datetime
    """The read time **of record** — on a re-open this is the original first
    read, not the current instant, because the endpoint is idempotent and
    ``announcement_reads`` stores first-read only."""


__all__ = [
    "AnnouncementReadReceiptDTO",
    "StudentAnnouncementDTO",
    "StudentAnnouncementsPageDTO",
    "UnreadAnnouncementCountDTO",
]
