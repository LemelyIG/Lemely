"""Tutoring marketplace API DTOs (``docs/tutoring/SPEC.md`` §b.3, rev 3).

Every class in SPEC §b.3's code block, with its fields, types and defaults
exactly as written there; ``tests/test_schemas_tutoring.py`` parses that block
and pins this module to it. The admin DTOs live in
:mod:`lemely.web.schemas_tutoring_admin`, and ``web/src/lib/tutoringTypes.ts``
mirrors both modules field for field (``tutoringTypesParity.test.ts``).

Style follows :mod:`lemely.web.schemas_student_classes`: one explicit
:class:`~lemely.web.schemas.ApiModel` subclass per DTO (``extra="forbid"``),
camelCase names declared directly. Instants are ISO-8601 strings with an
offset (SPEC §0 "Times"); ids are UUID strings.

Rules a builder must keep, because a type cannot:

* **Public fields (SPEC §a.5, row 5b).** The open web gets the public card and
  nothing else, ever: ``TutorCardDTO`` and what it nests, ``indexable`` on
  ``PublicTutorCardDTO`` only (row 17, O31).
* **Identifiers (SC-19, O29).** ``tutorId`` is always a ``tutor_profiles.id``,
  never a ``users.id``; no DTO here carries an email address.
* **Viewer-dependent serialisation (§b.3).** One builder per DTO, taking the
  viewer: ``BookingDTO.review``/``reviewOpensAt`` for the student viewer only
  (SC-12); ``studentShared`` for the tutor viewer only; ``meetingLink`` and
  ``locationDetail`` after accept to the student, the tutor and linked parents
  only (O16); a system ``cancelReason`` reads "Cancelled" to the tutor (SC-11);
  ``GrantDTO.alsoTeachesClasses`` for the student viewer only.
* **Names (F12).** A student's name shown to a tutor is
  ``core.tutor_directory.student_label(...)``, never an email fallback. No
  tutor-facing DTO reveals whether a student has linked parents (SC-9).
* **Free text (SC-7).** Lengths and contact-detail checks on request bodies are
  enforced by the service of each route (several are "after strip" or need a
  specific 422 code), so the request DTOs carry plain types as §b.3 does.
"""

from __future__ import annotations

from typing import Literal

from lemely.web.schemas import ApiModel
from lemely.web.schemas_analytics import (
    StudentDetailDTO,  # noqa: TC001 - pydantic needs the real type at runtime
)

TutoringModeLit = Literal["virtual", "in_person", "other"]
EffectiveStateLit = Literal[
    "requested",
    "accepted",
    "declined",
    "cancelled",
    "completed",
    "no_show",
    "expired",
    "awaiting_outcome",
]
ViewerActionLit = Literal[
    "accept",
    "decline",
    "cancel",
    "cancel_with_reason",
    "complete",
    "no_show",
    "review",
    "post_note",
]
"""``cancel_with_reason``: tutor viewer only, accepted booking inside 24 h of the
start (row 18); the client must collect a reason. ``cancel`` and
``cancel_with_reason`` are never both present."""
GrantStatusLit = Literal[
    "active",
    "revoked",
    "expired",
    "blocked",
    "tutor_suspended",
    "tutor_closed",
    "tutor_unavailable",
]


# ── Directory and public card (P1-P3, SP1-SP2) ───────────────────────────────


class SubjectRefDTO(ApiModel):
    """A subject by code and display name."""

    code: str
    name: str


class AreaRefDTO(ApiModel):
    """A city-level area from ``lemely/data/tutoring_areas.json``."""

    code: str
    name: str


class AreaListDTO(ApiModel):
    """P3: every tutoring area."""

    items: list[AreaRefDTO]


class RatingDTO(ApiModel):
    """A tutor's rating: "New" below three students, never stars (row 6)."""

    state: Literal["new", "rated"]
    average: float | None
    """One decimal place; ``None`` while ``state`` is ``"new"``."""
    count: int
    """Distinct students with a counted review (SC-16)."""


class TutorCardDTO(ApiModel):
    """The public card (row 5b): the only tutor fields the open web ever sees."""

    tutorId: str
    """``tutor_profiles.id``, never ``users.id`` (SC-19)."""
    publicName: str
    headline: str
    subjects: list[SubjectRefDTO]
    modes: list[TutoringModeLit]
    area: AreaRefDTO
    rating: RatingDTO


class PublicTutorCardDTO(TutorCardDTO):
    """P2 only (row 17): the card plus ``indexable``, read by the edge worker."""

    indexable: bool


class DirectoryFacetsDTO(ApiModel):
    """Filter options for the directory's first page."""

    subjects: list[SubjectRefDTO]
    areas: list[AreaRefDTO]


class PublicDirectoryPageDTO(ApiModel):
    """P1: one keyset page of public cards; ``facets`` on the first page only."""

    items: list[TutorCardDTO]
    nextCursor: str | None
    facets: DirectoryFacetsDTO | None


class DirectoryPageDTO(PublicDirectoryPageDTO):
    """SP1: the logged-in directory page (same shape as P1)."""


class AvailabilityRuleDTO(ApiModel):
    """A weekly rule, tutor-zone wall clock (Monday = 1; minutes from midnight)."""

    isoWeekday: int
    startMinute: int
    endMinute: int


class TutorProfileDTO(TutorCardDTO):
    """SP2: the full profile, logged-in only."""

    bio: str
    qualificationNote: str | None
    otherModeNote: str | None
    documentsSeen: bool
    """Lemely looked at uploaded documents; "documents seen" means only this."""
    availability: list[AvailabilityRuleDTO]
    zone: str
    zoneLabel: str
    listedSince: str | None
    """``"YYYY-MM"`` from ``first_listed_at``; ``None`` until the first approval.
    A never-listed profile (a draft, or one still under first review) has no
    value, and a builder never invents one."""


# ── Reviews (SP3, T18, T21, S6, S7) ──────────────────────────────────────────


class ReplyDTO(ApiModel):
    """A tutor's one reply to a review."""

    replyId: str
    body: str
    textState: Literal["pending", "approved", "rejected"]
    createdAt: str


class ReviewDTO(ApiModel):
    """SP3: a review as others see it: "A student", a quarter, never a name (SC-12)."""

    reviewId: str
    stars: int
    text: str | None
    period: str
    """The quarter, from ``core.tutor_ratings.quarter_label`` (SC-12)."""
    reply: ReplyDTO | None


class ReviewsPageDTO(ApiModel):
    """SP3: newest first; text and reply only when approved."""

    items: list[ReviewDTO]
    nextCursor: str | None


class TutorReviewItemDTO(ReviewDTO):
    """T21: a review of the caller's profile.

    ``text`` is ``None`` unless approved; the tutor's own reply in any state.
    """

    textState: Literal["none", "pending", "approved", "rejected"]


class TutorReviewsPageDTO(ApiModel):
    """T21: the caller's reviews, newest first."""

    items: list[TutorReviewItemDTO]
    nextCursor: str | None


# ── Outcomes (SP4, T8; ADR-T04) ──────────────────────────────────────────────


class OutcomeBucketDTO(ApiModel):
    """Students on one grade of the ladder."""

    grade: str
    count: int


class OutcomeDistributionDTO(ApiModel):
    """The grade distribution figure; counts are ``None`` when insufficient."""

    state: Literal["insufficient", "sufficient"]
    k: int
    nGraded: int | None
    nWithoutGrade: int | None
    buckets: list[OutcomeBucketDTO]
    """Empty when ``state`` is ``"insufficient"``."""


class OutcomeChangeDTO(ApiModel):
    """The higher/same/lower change figure; counts are ``None`` when insufficient."""

    state: Literal["insufficient", "sufficient"]
    k: int
    nPaired: int | None
    higher: int | None
    same: int | None
    lower: int | None


class SubjectOutcomeDTO(ApiModel):
    """Both figures for one subject."""

    subject: SubjectRefDTO
    distribution: OutcomeDistributionDTO
    change: OutcomeChangeDTO


class OutcomesDTO(ApiModel):
    """SP4: a tutor's outcome figures, per subject."""

    tutorId: str
    ladder: list[str]
    duringWindowDays: int
    beforeLookbackDays: int
    subjects: list[SubjectOutcomeDTO]


class TutorPreviewDTO(ApiModel):
    """T8: the profile as students see it; ``outcomes`` only when listed or under review."""

    profile: TutorProfileDTO
    outcomes: OutcomesDTO | None


# ── Slots and bookings (SP5, SP6, S1-S5, S14, T9-T17, PA1-PA5) ──────────────


class SlotDTO(ApiModel):
    """One bookable start and end instant."""

    startsAt: str
    endsAt: str


class SlotsDTO(ApiModel):
    """SP5: bookable slots in a window, labelled in the tutor's zone."""

    tutorId: str
    zone: str
    zoneLabel: str
    durationMinutes: int
    windowStart: str
    windowEnd: str
    slots: list[SlotDTO]


class BookingCreateDTO(ApiModel):
    """SP6 body. A parent must send ``studentId``; only a student may send ``firstNote``."""

    tutorId: str
    studentId: str | None = None
    subjectCode: str
    mode: TutoringModeLit
    startsAt: str
    durationMinutes: int
    otherModeNote: str | None = None
    firstNote: str | None = None
    """Student requester only; from a parent it is refused with 422 (F19)."""


class BookingStudentDTO(ApiModel):
    """The booking's student, labelled by ``student_label()``, never an email (F12)."""

    studentId: str
    displayName: str


class BookingReviewRefDTO(ApiModel):
    """The student's own review of this booking (student viewer only, SC-12)."""

    reviewId: str
    stars: int
    textState: Literal["none", "pending", "approved", "rejected"]
    editableUntil: str


class BookingDTO(ApiModel):
    """One booking, serialised for its viewer (see the module docstring)."""

    bookingId: str
    tutor: TutorCardDTO
    student: BookingStudentDTO
    requestedBy: Literal["student", "parent"]
    subject: SubjectRefDTO
    mode: TutoringModeLit
    startsAt: str
    endsAt: str
    effectiveState: EffectiveStateLit
    area: AreaRefDTO
    meetingLink: str | None
    """After accept only, to participants and linked parents (O16)."""
    locationDetail: str | None
    """After accept only, to participants and linked parents (O16)."""
    otherModeNote: str | None
    declineReason: str | None
    cancelReason: str | None
    """A system reason reads "Cancelled" for the tutor viewer (SC-11)."""
    cancelledBy: Literal["student", "parent", "tutor", "platform_admin", "system"] | None
    cancelledLate: bool
    """The tutor cancelled inside 24 h of the start (row 18): ``cancelled_by_party =
    'tutor' AND cancelled_at > starts_at - CANCEL_CUTOFF``."""
    completedBy: Literal["student", "parent", "tutor", "platform_admin"] | None
    notesFrozen: bool
    allowedActions: list[ViewerActionLit]
    review: BookingReviewRefDTO | None
    """Student viewer only; ``None`` for every other viewer (SC-12)."""
    reviewOpensAt: str | None
    """Student viewer only."""
    studentShared: bool | None
    """Tutor viewer only: the grant predicate, with no audit row (F13)."""
    createdAt: str


class BookingsPageDTO(ApiModel):
    """S1, T9, PA1: one keyset page of bookings."""

    items: list[BookingDTO]
    nextCursor: str | None


class BookingAcceptDTO(ApiModel):
    """T11 body: an allowlisted link for virtual, a place for in-person (SC-7)."""

    meetingLink: str | None = None
    locationDetail: str | None = None


class BookingReasonDTO(ApiModel):
    """S3, T12, T13, PA4 body: an optional reason (at most 300 characters, SC-7).

    Required from a tutor cancelling inside 24 h of the start (row 18).
    """

    reason: str | None = None


# ── Notes (S4, S5, T16, T17, PA3) ─────────────────────────────────────────────


class NoteDTO(ApiModel):
    """One note in a booking's thread; a hidden note has ``body`` ``None``."""

    noteId: str
    authorParty: Literal["student", "tutor"]
    authorName: str
    body: str | None
    hidden: bool
    createdAt: str


class NotesPageDTO(ApiModel):
    """A booking's notes, oldest first; ``canPost`` is always false for parents."""

    items: list[NoteDTO]
    nextCursor: str | None
    canPost: bool


class NoteCreateDTO(ApiModel):
    """S5, T17 body: 1 to 2000 characters after strip (service-checked)."""

    body: str


class ReviewCreateDTO(ApiModel):
    """S6 body."""

    stars: int
    text: str | None = None


class ReviewUpdateDTO(ApiModel):
    """S7 body; ``clearText`` removes the text, inside the 14-day window."""

    stars: int | None = None
    text: str | None = None
    clearText: bool = False


class MyReviewDTO(ApiModel):
    """S6, S7: the student's own review."""

    reviewId: str
    bookingId: str
    stars: int
    text: str | None
    textState: Literal["none", "pending", "approved", "rejected"]
    editableUntil: str


class ReplyCreateDTO(ApiModel):
    """T18 body."""

    body: str


# ── Grants, access log and settings (S8-S13, S15, S16, PA6, PA7) ─────────────


class GrantDTO(ApiModel):
    """One data grant, as the student (or, read-only, a linked parent) sees it."""

    grantId: str
    tutor: TutorCardDTO
    createdAt: str
    revokedAt: str | None
    status: GrantStatusLit
    scope: Literal["all_subjects_derived"]
    alsoTeachesClasses: list[str]
    """Student viewer: class names whose teacher is this tutor's user (SC-2e);
    always empty for parents."""


class GrantsDTO(ApiModel):
    """S8, PA6: live grants first, then ended ones, newest first."""

    items: list[GrantDTO]


class GrantCreateDTO(ApiModel):
    """S9 body."""

    tutorId: str


class AccessLogEntryDTO(ApiModel):
    """One tutor read of the student's data. Carries no entry id (ID-5)."""

    tutorId: str | None
    tutorName: str
    action: Literal["list", "detail"]
    accessedAt: str


class AccessLogPageDTO(ApiModel):
    """S11, PA7: newest first."""

    items: list[AccessLogEntryDTO]
    nextCursor: str | None


class TutoringSettingsDTO(ApiModel):
    """S12, S13, S15: the student's own tutoring preferences."""

    outcomeStatsOptOut: bool
    outcomePrefChangedAt: str | None
    safetyNoticeAcknowledgedAt: str | None


class TutoringSettingsUpdateDTO(ApiModel):
    """S13 body."""

    outcomeStatsOptOut: bool


class ClassAccessItemDTO(ApiModel):
    """S16: a class whose teacher sees the caller's progress through the roster."""

    classId: str
    className: str
    teacherName: str
    schoolName: str | None
    leavable: bool
    """True exactly for a school-less class (S17)."""
    teacherIsYourTutor: bool
    """The class teacher holds a tutor profile with which the caller has a
    booking or a grant (XT-2)."""


class ClassAccessDTO(ApiModel):
    """S16 response."""

    items: list[ClassAccessItemDTO]


# ── Tutor profile and onboarding (T1-T7) ─────────────────────────────────────


class EvidenceDTO(ApiModel):
    """One evidence file's metadata; the file itself is never served here (O17)."""

    evidenceId: str
    filename: str
    contentType: str
    sizeBytes: int
    description: str | None
    uploadedAt: str


class TutorProfileCreateDTO(ApiModel):
    """T2 body."""

    publicFirstName: str
    publicLastInitial: str | None = None
    headline: str
    bio: str = ""
    qualificationNote: str | None = None
    subjectCodes: list[str]
    """1 to 10 subject codes."""
    offersVirtual: bool
    offersInPerson: bool
    offersOther: bool
    otherModeNote: str | None = None
    areaCode: str


class TutorProfileUpdateDTO(ApiModel):
    """T3 body: every field of the create body, optional, plus two toggles.

    An omitted field is left unchanged. ``paused`` and ``indexable`` are not
    moderated, so changing them never sends a listed profile back to review.
    """

    publicFirstName: str | None = None
    publicLastInitial: str | None = None
    headline: str | None = None
    bio: str | None = None
    qualificationNote: str | None = None
    subjectCodes: list[str] | None = None
    offersVirtual: bool | None = None
    offersInPerson: bool | None = None
    offersOther: bool | None = None
    otherModeNote: str | None = None
    areaCode: str | None = None
    paused: bool | None = None
    indexable: bool | None = None
    """Row 17: search engines may index the public card while true."""


class TutorOwnProfileDTO(TutorProfileDTO):
    """T1-T4: the caller's own profile, with its listing state and evidence."""

    listingState: Literal["draft", "pending_review", "listed", "rejected", "suspended", "closed"]
    paused: bool
    indexable: bool
    submittedAt: str | None
    reviewNote: str | None
    """The rejection or suspension note, shown to the tutor."""
    evidence: list[EvidenceDTO]
    reReviewRequired: bool = False
    """T3: this edit sent a listed profile back to review."""


class AvailabilityReplaceDTO(ApiModel):
    """T5 body: 0 to 42 weekly rules."""

    rules: list[AvailabilityRuleDTO]


# ── The tutor's students (T19, T20) ──────────────────────────────────────────


class TutorStudentItemDTO(ApiModel):
    """T19: one student with a valid grant; no analytics."""

    studentId: str
    displayName: str
    grantId: str
    grantedAt: str
    upcomingSessions: int


class TutorStudentPageDTO(ApiModel):
    """T19: ``grantedAt`` descending, then ``grantId``."""

    items: list[TutorStudentItemDTO]
    nextCursor: str | None


class TutorStudentDetailDTO(ApiModel):
    """T20: the T-05 student detail through the tutor projection (SPEC §e.2, SC-20)."""

    detail: StudentDetailDTO
    grantId: str
    grantedAt: str
    accessRecordedAt: str


# ── Safety: reports and blocks (R1, B1-B3) ───────────────────────────────────


class ReportCreateDTO(ApiModel):
    """R1 body."""

    targetType: Literal["tutor_profile", "review", "review_reply", "booking", "booking_note"]
    targetId: str
    reason: Literal[
        "safety_concern",
        "inappropriate_content",
        "harassment",
        "spam",
        "fake_profile",
        "disputed_outcome",
        "other",
    ]
    details: str | None = None


class ReportReceiptDTO(ApiModel):
    """R1 response."""

    reportId: str
    createdAt: str


class BlockCreateDTO(ApiModel):
    """B2 body: exactly one of ``tutorId`` (student caller) or ``studentId`` (tutor caller)."""

    tutorId: str | None = None
    studentId: str | None = None


class BlockDTO(ApiModel):
    """One active block, named for the caller (SC-19)."""

    counterpartId: str
    """A tutor profile id for a student viewer; a student id for a tutor viewer."""
    displayName: str
    """The tutor's public name, or ``student_label()``; never a full account name."""
    createdAt: str


class BlocksDTO(ApiModel):
    """B1 response: active blocks only."""

    items: list[BlockDTO]


__all__ = [
    "AccessLogEntryDTO",
    "AccessLogPageDTO",
    "AreaListDTO",
    "AreaRefDTO",
    "AvailabilityReplaceDTO",
    "AvailabilityRuleDTO",
    "BlockCreateDTO",
    "BlockDTO",
    "BlocksDTO",
    "BookingAcceptDTO",
    "BookingCreateDTO",
    "BookingDTO",
    "BookingReasonDTO",
    "BookingReviewRefDTO",
    "BookingStudentDTO",
    "BookingsPageDTO",
    "ClassAccessDTO",
    "ClassAccessItemDTO",
    "DirectoryFacetsDTO",
    "DirectoryPageDTO",
    "EffectiveStateLit",
    "EvidenceDTO",
    "GrantCreateDTO",
    "GrantDTO",
    "GrantStatusLit",
    "GrantsDTO",
    "MyReviewDTO",
    "NoteCreateDTO",
    "NoteDTO",
    "NotesPageDTO",
    "OutcomeBucketDTO",
    "OutcomeChangeDTO",
    "OutcomeDistributionDTO",
    "OutcomesDTO",
    "PublicDirectoryPageDTO",
    "PublicTutorCardDTO",
    "RatingDTO",
    "ReplyCreateDTO",
    "ReplyDTO",
    "ReportCreateDTO",
    "ReportReceiptDTO",
    "ReviewCreateDTO",
    "ReviewDTO",
    "ReviewUpdateDTO",
    "ReviewsPageDTO",
    "SlotDTO",
    "SlotsDTO",
    "SubjectOutcomeDTO",
    "SubjectRefDTO",
    "TutorCardDTO",
    "TutorOwnProfileDTO",
    "TutorPreviewDTO",
    "TutorProfileCreateDTO",
    "TutorProfileDTO",
    "TutorProfileUpdateDTO",
    "TutorReviewItemDTO",
    "TutorReviewsPageDTO",
    "TutorStudentDetailDTO",
    "TutorStudentItemDTO",
    "TutorStudentPageDTO",
    "TutoringModeLit",
    "TutoringSettingsDTO",
    "TutoringSettingsUpdateDTO",
    "ViewerActionLit",
]
