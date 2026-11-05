"""Platform-admin tutoring DTOs (``docs/tutoring/SPEC.md`` §b.3 admin list).

SPEC §b.3 names these classes but gives fields for only a few of them. The
field sets here are derived from the admin routes (§b.2 A1-A12) and screens
(§d X-04..X-07); the T04 hand-off (``BUILD/tutoring/handoffs/T04.md``) lists
every field with the SPEC line it comes from. The rule throughout is SPEC
§a.5: an admin gets what moderation needs and nothing more.

* **Admin-only data (§a.5).** ``accountEmail`` (A2, X-05), evidence download
  URLs (A2, O17), approval notes and the report ``snapshot`` appear here and
  nowhere else. Each signed URL and each report-thread read is logged in
  ``tutoring_admin_access`` by the route that issues it (SC-23).
* **Never to an admin.** No field of ``StudentDetailDTO`` (ADR-T03), no meeting
  link (O16), no student name or id (§a.5: a student's name goes to their
  tutor, their parents and themselves only), no admin user id and no log row id
  (ID-5). The one place an admin reads is a reported booking's
  ``AdminBookingSummaryDTO.locationDetail``: an in-person safety concern may
  need it (fix lane F7-25).
"""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue  # noqa: TC002 - pydantic needs the real type at runtime

from lemely.web.schemas import ApiModel
from lemely.web.schemas_tutoring import (
    EffectiveStateLit,
    EvidenceDTO,
    NoteDTO,
    SubjectRefDTO,
    TutoringModeLit,
    TutorProfileDTO,
)

ReportResolutionLit = Literal[
    "dismissed",
    "content_hidden",
    "tutor_suspended",
    "booking_cancelled",
    "booking_completed",
]
"""``reportresolution`` (SPEC §a.1): X-07's dismiss / hide content / suspend
tutor / cancel booking / mark completed."""

# ── Tutor approval (A1-A5, A12; X-04, X-05) ──────────────────────────────────


class AdminTutorItemDTO(ApiModel):
    """A1: one row of the X-04 approval queue ("name, subjects, submitted")."""

    tutorId: str
    """The profile id X-05 opens (A2)."""
    publicName: str
    subjects: list[SubjectRefDTO]
    submittedAt: str | None
    """The last submit for review; ``None`` for a profile never submitted."""


class AdminTutorPageDTO(ApiModel):
    """A1: one keyset page of the queue, filtered by ``state``."""

    items: list[AdminTutorItemDTO]
    nextCursor: str | None
    emailDelivery: Literal["provider", "mock"]
    """SC-6: X-04 shows "Email delivery: mock" when no provider is configured."""


class AdminEvidenceDTO(EvidenceDTO):
    """One evidence file with its download link (O17)."""

    signedUrl: str | None
    """A 300 s ``attachment`` URL, issued and logged by A2 only (O17, SC-23);
    ``None`` on the A3, A4, A5 and A12 responses, which reuse the detail DTO."""


class AdminApprovalEventDTO(ApiModel):
    """One ``tutor_approval_events`` row in X-05's approval history.

    Carries no event id and no admin user id (ID-5): the history is the
    sequence of decisions and their notes.
    """

    decision: Literal["approved", "rejected", "suspended", "reinstated", "closed"]
    documentsSeen: bool
    note: str | None
    """Admin-internal, except a rejection or suspension note, which the tutor
    also sees."""
    createdAt: str


class AdminTutorDetailDTO(TutorProfileDTO):
    """A2-A5, A12: X-05's tutor application.

    Every ``TutorOwnProfileDTO`` field (restated, because ``evidence`` carries
    the admin row type) plus the account email, the approval history and the
    open report count.
    """

    listingState: Literal["draft", "pending_review", "listed", "rejected", "suspended", "closed"]
    paused: bool
    indexable: bool
    submittedAt: str | None
    reviewNote: str | None
    evidence: list[AdminEvidenceDTO]
    reReviewRequired: bool = False
    """Kept from ``TutorOwnProfileDTO``; always false on admin responses."""
    accountEmail: str
    """``users.email`` of the tutor's account: admin only, X-05 only (§a.5, EM-5)."""
    history: list[AdminApprovalEventDTO]
    """Newest first."""
    openReports: int
    """Reports in state ``open`` whose target belongs to this tutor."""


class AdminApproveDTO(ApiModel):
    """A3 body: approve, or reinstate a suspended tutor.

    ``documentsSeen`` is the X-05 "I looked at the documents" checkbox: true
    sets ``documents_seen_at``, false clears it.
    """

    documentsSeen: bool
    note: str | None = None


class AdminNoteDTO(ApiModel):
    """A4, A5, A12 body. The service requires the note for a rejection (§a.3)."""

    note: str | None = None


# ── Moderation (A6-A8; X-06) ─────────────────────────────────────────────────


class ModerationItemDTO(ApiModel):
    """A6: one review text or reply awaiting moderation (X-06).

    No reviewer identity and no booking reference (SC-12): moderation judges
    the text.
    """

    kind: Literal["review", "reply"]
    itemId: str
    """The review id (A7) or the reply id (A8), as ``kind`` says."""
    text: str
    createdAt: str
    revision: str
    """The first 16 hex characters of the SHA-256 of ``text`` (RF-7). A7 sends it
    back, so a review text edited after this page was loaded is never approved
    unseen."""


class ModerationPageDTO(ApiModel):
    """A6: oldest first."""

    items: list[ModerationItemDTO]
    nextCursor: str | None


class ReviewModerateDTO(ApiModel):
    """A7 body."""

    decision: Literal["approved", "rejected"]
    revision: str
    """The ``ModerationItemDTO.revision`` the admin was shown. Compared with the
    stored text under the row lock: a mismatch is 409 ``text_changed``."""


class ReplyModerateDTO(ApiModel):
    """A8 body. No revision: a reply cannot be edited (RF-7)."""

    decision: Literal["approved", "rejected"]


class AdminReviewDTO(ApiModel):
    """A7 response: the review after moderation, without its author (SC-12)."""

    reviewId: str
    stars: int
    text: str | None
    textState: Literal["none", "pending", "approved", "rejected"]
    createdAt: str


class AdminReplyDTO(ApiModel):
    """A8 response: the reply after moderation."""

    replyId: str
    body: str
    textState: Literal["pending", "approved", "rejected"]
    createdAt: str


# ── Reports (A9-A11; X-07) ───────────────────────────────────────────────────


class ReportItemDTO(ApiModel):
    """A9: one row of the X-07 queue, safety concerns first."""

    reportId: str
    targetType: Literal["tutor_profile", "review", "review_reply", "booking", "booking_note"]
    reason: Literal[
        "safety_concern",
        "inappropriate_content",
        "harassment",
        "spam",
        "fake_profile",
        "disputed_outcome",
        "other",
    ]
    state: Literal["open", "dismissed", "actioned"]
    createdAt: str


class ReportPageDTO(ApiModel):
    """A9: one keyset page, filtered by ``state``."""

    items: list[ReportItemDTO]
    nextCursor: str | None


class AdminBookingSummaryDTO(ApiModel):
    """The booking a booking or note report concerns (A10 "booking summary").

    What X-07's resolutions turn on: the start (cancel before start only), the
    effective state (mark completed only from ``awaiting_outcome`` or
    ``no_show``), who recorded completion (SC-17) and the notes freeze (SC-10).
    And what a booking report is usually about: the tutor's own words on the
    booking and where an in-person session meets. No student and no meeting
    link (§a.5, O16).
    """

    bookingId: str
    subject: SubjectRefDTO
    mode: TutoringModeLit
    startsAt: str
    endsAt: str
    effectiveState: EffectiveStateLit
    completedBy: Literal["student", "parent", "tutor", "platform_admin"] | None
    notesFrozen: bool
    declineReason: str | None
    """The tutor's reason for declining the request."""
    cancelReason: str | None
    """The tutor's own reason when the tutor cancelled; "This session was
    cancelled by Lemely." when the platform or the system did (fixed literals);
    ``None`` for a student's or parent's cancellation."""
    locationDetail: str | None
    """Where an in-person session meets (an in-person safety concern may need
    it). Never the meeting link of a virtual one."""
    otherModeNote: str | None
    """The note on an "other" session."""


class ReportDetailDTO(ReportItemDTO):
    """A10, A11: one report with what it points at (X-07).

    ``notes`` is the only admin path to a notes thread (O15); A10 logs each view
    (SC-23). A hidden note's body is visible here. A student author is named by
    party, never by name (§a.5).
    """

    reporterParty: Literal["student", "parent", "tutor"]
    details: str | None
    """The reporter's own words (R1 ``details``)."""
    tutorId: str
    """The tutor profile the target belongs to: the one a ``tutor_suspended``
    resolution suspends."""
    tutorName: str
    """That tutor's public name."""
    tutorListingState: Literal[
        "draft", "pending_review", "listed", "rejected", "suspended", "closed"
    ]
    """That tutor's listing state now: X-07 offers ``tutor_suspended`` only from
    ``pending_review``, ``listed`` or ``rejected`` (A11 accepts it as already
    done once ``suspended`` or ``closed``)."""
    snapshot: dict[str, JsonValue]
    """``target_snapshot``: the reported content as it was when reported
    (admin only, §a.5). A11's answer leaves out a note target's ``body``: A10 is
    the one logged path to notes (O15)."""
    bookingSummary: AdminBookingSummaryDTO | None
    """Booking and note targets only."""
    notes: list[NoteDTO]
    """The booking's thread for booking and note targets on A10; empty otherwise,
    and always empty on A11."""
    resolution: ReportResolutionLit | None
    resolutionNote: str | None
    resolvedAt: str | None


class ReportResolveDTO(ApiModel):
    """A11 body: X-07's five resolutions and a note."""

    resolution: ReportResolutionLit
    note: str | None = None


__all__ = [
    "AdminApprovalEventDTO",
    "AdminApproveDTO",
    "AdminBookingSummaryDTO",
    "AdminEvidenceDTO",
    "AdminNoteDTO",
    "AdminReplyDTO",
    "AdminReviewDTO",
    "AdminTutorDetailDTO",
    "AdminTutorItemDTO",
    "AdminTutorPageDTO",
    "ModerationItemDTO",
    "ModerationPageDTO",
    "ReplyModerateDTO",
    "ReportDetailDTO",
    "ReportItemDTO",
    "ReportPageDTO",
    "ReportResolutionLit",
    "ReportResolveDTO",
    "ReviewModerateDTO",
]
