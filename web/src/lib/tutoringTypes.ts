/*
 * TS interfaces mirroring `lemely/web/schemas_tutoring.py` and
 * `lemely/web/schemas_tutoring_admin.py` field for field (camelCase): the
 * tutoring marketplace API contract, `docs/tutoring/SPEC.md` §b.3.
 *
 * Naming follows `teacherTypes.ts`: the Python class name without its `DTO`
 * suffix (`TutorCardDTO` -> `TutorCard`), and a Python `…Lit` literal alias
 * without `Lit` (`TutoringModeLit` -> `TutoringMode`). A Python subclass is an
 * interface that `extends` its parent's mirror. A Python field with a default
 * is optional here; `X | None` is `X | null`. `tutoringTypesParity.test.ts`
 * parses both Python files and fails on any drift in a name, a type, an
 * optional mark or a parent.
 *
 * Rules a type cannot carry (the Python module docstrings have the detail):
 *   - The open web gets the public card and nothing else (SPEC §a.5, row 5b).
 *     `indexable` is on `PublicTutorCard`, the tutor's own profile and the
 *     admin detail only (row 17, O31).
 *   - `tutorId` is always a tutor profile id, never an account id (SC-19).
 *   - `Booking` is serialised per viewer: `review`/`reviewOpensAt` for the
 *     student, `studentShared` for the tutor, `meetingLink`/`locationDetail`
 *     after accept to participants and linked parents only (O16).
 *   - Render every free-text field as plain text, never auto-linked (SC-7).
 *   - Admin types (the last section) are reachable by `platform_admin` only.
 */

import type { StudentDetail } from "./teacherTypes"

// ── Literal unions ──────────────────────────────────────────────────────────

export type TutoringMode = "virtual" | "in_person" | "other"

export type EffectiveState = "requested" | "accepted" | "declined" | "cancelled" | "completed" | "no_show" | "expired" | "awaiting_outcome"

/** `cancel_with_reason`: tutor viewer only, accepted booking inside 24 h of
 * the start (row 18); collect a reason. Never present together with `cancel`. */
export type ViewerAction = "accept" | "decline" | "cancel" | "cancel_with_reason" | "complete" | "no_show" | "review" | "post_note"

export type GrantStatus = "active" | "revoked" | "expired" | "blocked" | "tutor_suspended" | "tutor_closed" | "tutor_unavailable"

/** X-07's five report resolutions (`reportresolution`). */
export type ReportResolution = "dismissed" | "content_hidden" | "tutor_suspended" | "booking_cancelled" | "booking_completed"

/** Any JSON value: the type of a report's `snapshot` (pydantic `JsonValue`). */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

// ── Directory and public card (P1-P3, SP1-SP2) ─────────────────────────────

export interface SubjectRef {
  code: string
  name: string
}

export interface AreaRef {
  code: string
  name: string
}

/** `GET /api/public/tutoring-areas` (P3). */
export interface AreaList {
  items: AreaRef[]
}

/** "New" below three students, never stars (row 6). `average` has one
 * decimal place and is null while new; `count` is distinct students. */
export interface Rating {
  state: "new" | "rated"
  average: number | null
  count: number
}

/** The public card (row 5b): the only tutor fields the open web ever sees. */
export interface TutorCard {
  tutorId: string
  publicName: string
  headline: string
  subjects: SubjectRef[]
  modes: TutoringMode[]
  area: AreaRef
  rating: Rating
}

/** `GET /api/public/tutors/{id}` (P2): the card plus `indexable` (row 17). */
export interface PublicTutorCard extends TutorCard {
  indexable: boolean
}

export interface DirectoryFacets {
  subjects: SubjectRef[]
  areas: AreaRef[]
}

/** `GET /api/public/tutors` (P1); `facets` on the first page only. */
export interface PublicDirectoryPage {
  items: TutorCard[]
  nextCursor: string | null
  facets: DirectoryFacets | null
}

/** `GET /api/tutors` (SP1): same shape as P1. */
export interface DirectoryPage extends PublicDirectoryPage {
}

/** A weekly rule in the tutor's zone (Monday = 1; minutes from midnight). */
export interface AvailabilityRule {
  isoWeekday: number
  startMinute: number
  endMinute: number
}

/** `GET /api/tutors/{id}` (SP2): the full profile, logged-in only.
 * `listedSince` is "YYYY-MM" from the first approval, and null until then
 * (a draft, or a profile still under its first review). */
export interface TutorProfile extends TutorCard {
  bio: string
  qualificationNote: string | null
  otherModeNote: string | null
  documentsSeen: boolean
  availability: AvailabilityRule[]
  zone: string
  zoneLabel: string
  listedSince: string | null
}

// ── Reviews (SP3, T18, T21, S6, S7) ────────────────────────────────────────

export interface Reply {
  replyId: string
  body: string
  textState: "pending" | "approved" | "rejected"
  createdAt: string
}

/** A review as others see it: "A student" and a quarter, never a name (SC-12). */
export interface Review {
  reviewId: string
  stars: number
  text: string | null
  period: string
  reply: Reply | null
}

export interface ReviewsPage {
  items: Review[]
  nextCursor: string | null
}

/** `GET /api/tutor/reviews` (T21): `text` null unless approved; the own
 * reply in any moderation state. */
export interface TutorReviewItem extends Review {
  textState: "none" | "pending" | "approved" | "rejected"
}

export interface TutorReviewsPage {
  items: TutorReviewItem[]
  nextCursor: string | null
}

// ── Outcomes (SP4, T8; ADR-T04) ────────────────────────────────────────────

export interface OutcomeBucket {
  grade: string
  count: number
}

/** Counts are null and `buckets` empty when `state` is "insufficient". */
export interface OutcomeDistribution {
  state: "insufficient" | "sufficient"
  k: number
  nGraded: number | null
  nWithoutGrade: number | null
  buckets: OutcomeBucket[]
}

/** The higher/same/lower figure; counts are null when "insufficient". */
export interface OutcomeChange {
  state: "insufficient" | "sufficient"
  k: number
  nPaired: number | null
  higher: number | null
  same: number | null
  lower: number | null
}

export interface SubjectOutcome {
  subject: SubjectRef
  distribution: OutcomeDistribution
  change: OutcomeChange
}

export interface Outcomes {
  tutorId: string
  ladder: string[]
  duringWindowDays: number
  beforeLookbackDays: number
  subjects: SubjectOutcome[]
}

/** `GET /api/tutor/profile/preview` (T8); `outcomes` only when listed or
 * under review. */
export interface TutorPreview {
  profile: TutorProfile
  outcomes: Outcomes | null
}

// ── Slots and bookings ─────────────────────────────────────────────────────

export interface Slot {
  startsAt: string
  endsAt: string
}

/** `GET /api/tutors/{id}/slots` (SP5). */
export interface Slots {
  tutorId: string
  zone: string
  zoneLabel: string
  durationMinutes: number
  windowStart: string
  windowEnd: string
  slots: Slot[]
}

/** `POST /api/bookings` (SP6). A parent sends `studentId`; only a student
 * may send `firstNote`. */
export interface BookingCreate {
  tutorId: string
  studentId?: string | null
  subjectCode: string
  mode: TutoringMode
  startsAt: string
  durationMinutes: number
  otherModeNote?: string | null
  firstNote?: string | null
}

/** The booking's student, by `student_label()`, never an email (F12). */
export interface BookingStudent {
  studentId: string
  displayName: string
}

/** The student's own review of the booking (student viewer only, SC-12). */
export interface BookingReviewRef {
  reviewId: string
  stars: number
  textState: "none" | "pending" | "approved" | "rejected"
  editableUntil: string
}

/** One booking, serialised for its viewer (see the header). `cancelledLate`:
 * the tutor cancelled inside 24 h of the start (row 18). */
export interface Booking {
  bookingId: string
  tutor: TutorCard
  student: BookingStudent
  requestedBy: "student" | "parent"
  subject: SubjectRef
  mode: TutoringMode
  startsAt: string
  endsAt: string
  effectiveState: EffectiveState
  area: AreaRef
  meetingLink: string | null
  locationDetail: string | null
  otherModeNote: string | null
  declineReason: string | null
  cancelReason: string | null
  cancelledBy: "student" | "parent" | "tutor" | "platform_admin" | "system" | null
  cancelledLate: boolean
  completedBy: "student" | "parent" | "tutor" | "platform_admin" | null
  notesFrozen: boolean
  allowedActions: ViewerAction[]
  review: BookingReviewRef | null
  reviewOpensAt: string | null
  studentShared: boolean | null
  createdAt: string
}

export interface BookingsPage {
  items: Booking[]
  nextCursor: string | null
}

/** `POST /api/tutor/bookings/{id}/accept` (T11). */
export interface BookingAccept {
  meetingLink?: string | null
  locationDetail?: string | null
}

/** Cancel and decline bodies. A tutor cancelling inside 24 h of the start
 * must send a reason (row 18). */
export interface BookingReason {
  reason?: string | null
}

// ── Notes ──────────────────────────────────────────────────────────────────

/** A hidden note has a null `body` (except in the admin report detail). */
export interface Note {
  noteId: string
  authorParty: "student" | "tutor"
  authorName: string
  body: string | null
  hidden: boolean
  createdAt: string
}

/** Oldest first; `canPost` is always false for parents. */
export interface NotesPage {
  items: Note[]
  nextCursor: string | null
  canPost: boolean
}

export interface NoteCreate {
  body: string
}

export interface ReviewCreate {
  stars: number
  text?: string | null
}

export interface ReviewUpdate {
  stars?: number | null
  text?: string | null
  clearText?: boolean
}

export interface MyReview {
  reviewId: string
  bookingId: string
  stars: number
  text: string | null
  textState: "none" | "pending" | "approved" | "rejected"
  editableUntil: string
}

export interface ReplyCreate {
  body: string
}

// ── Grants, access log and settings ────────────────────────────────────────

/** `alsoTeachesClasses`: student viewer only, always empty for parents. */
export interface Grant {
  grantId: string
  tutor: TutorCard
  createdAt: string
  revokedAt: string | null
  status: GrantStatus
  scope: "all_subjects_derived"
  alsoTeachesClasses: string[]
}

export interface Grants {
  items: Grant[]
}

export interface GrantCreate {
  tutorId: string
}

/** One tutor read of the student's data; carries no entry id (ID-5). */
export interface AccessLogEntry {
  tutorId: string | null
  tutorName: string
  action: "list" | "detail"
  accessedAt: string
}

export interface AccessLogPage {
  items: AccessLogEntry[]
  nextCursor: string | null
}

export interface TutoringSettings {
  outcomeStatsOptOut: boolean
  outcomePrefChangedAt: string | null
  safetyNoticeAcknowledgedAt: string | null
}

export interface TutoringSettingsUpdate {
  outcomeStatsOptOut: boolean
}

/** A class whose teacher sees the caller's progress (S16); `leavable` is
 * true exactly for a school-less class. */
export interface ClassAccessItem {
  classId: string
  className: string
  teacherName: string
  schoolName: string | null
  leavable: boolean
  teacherIsYourTutor: boolean
}

export interface ClassAccess {
  items: ClassAccessItem[]
}

// ── Tutor profile and onboarding (T1-T7) ───────────────────────────────────

/** Evidence metadata; the file itself is never served to non-admins (O17). */
export interface Evidence {
  evidenceId: string
  filename: string
  contentType: string
  sizeBytes: number
  description: string | null
  uploadedAt: string
}

export interface TutorProfileCreate {
  publicFirstName: string
  publicLastInitial?: string | null
  headline: string
  bio?: string
  qualificationNote?: string | null
  subjectCodes: string[]
  offersVirtual: boolean
  offersInPerson: boolean
  offersOther: boolean
  otherModeNote?: string | null
  areaCode: string
}

/** `PATCH /api/tutor/profile` (T3): an omitted field is left unchanged.
 * `paused` and `indexable` never send a listed profile back to review. */
export interface TutorProfileUpdate {
  publicFirstName?: string | null
  publicLastInitial?: string | null
  headline?: string | null
  bio?: string | null
  qualificationNote?: string | null
  subjectCodes?: string[] | null
  offersVirtual?: boolean | null
  offersInPerson?: boolean | null
  offersOther?: boolean | null
  otherModeNote?: string | null
  areaCode?: string | null
  paused?: boolean | null
  indexable?: boolean | null
}

/** The caller's own profile (T1-T4); `reReviewRequired` is set by T3. */
export interface TutorOwnProfile extends TutorProfile {
  listingState: "draft" | "pending_review" | "listed" | "rejected" | "suspended" | "closed"
  paused: boolean
  indexable: boolean
  submittedAt: string | null
  reviewNote: string | null
  evidence: Evidence[]
  reReviewRequired?: boolean
}

export interface AvailabilityReplace {
  rules: AvailabilityRule[]
}

// ── The tutor's students (T19, T20) ────────────────────────────────────────

export interface TutorStudentItem {
  studentId: string
  displayName: string
  grantId: string
  grantedAt: string
  upcomingSessions: number
}

export interface TutorStudentPage {
  items: TutorStudentItem[]
  nextCursor: string | null
}

/** `GET /api/tutor/students/{id}` (T20): the T-05 detail through the tutor
 * projection (dates only, no question ids; SPEC §e.2). */
export interface TutorStudentDetail {
  detail: StudentDetail
  grantId: string
  grantedAt: string
  accessRecordedAt: string
}

// ── Safety: reports and blocks ─────────────────────────────────────────────

export interface ReportCreate {
  targetType: "tutor_profile" | "review" | "review_reply" | "booking" | "booking_note"
  targetId: string
  reason: "safety_concern" | "inappropriate_content" | "harassment" | "spam" | "fake_profile" | "disputed_outcome" | "other"
  details?: string | null
}

export interface ReportReceipt {
  reportId: string
  createdAt: string
}

/** Exactly one field: `tutorId` from a student, `studentId` from a tutor. */
export interface BlockCreate {
  tutorId?: string | null
  studentId?: string | null
}

/** `counterpartId` is a tutor profile id (student viewer) or a student id
 * (tutor viewer); `displayName` is never a full account name. */
export interface Block {
  counterpartId: string
  displayName: string
  createdAt: string
}

export interface Blocks {
  items: Block[]
}

// ── Platform admin (`schemas_tutoring_admin.py`; X-04..X-07) ───────────────

/** One row of the X-04 approval queue. */
export interface AdminTutorItem {
  tutorId: string
  publicName: string
  subjects: SubjectRef[]
  submittedAt: string | null
}

/** `GET /api/admin/tutors` (A1); X-04 shows "Email delivery: mock" when
 * `emailDelivery` is "mock" (SC-6). */
export interface AdminTutorPage {
  items: AdminTutorItem[]
  nextCursor: string | null
  emailDelivery: "provider" | "mock"
}

/** `signedUrl` is a 300 s download link issued on A2 only and null on the
 * other routes that return the detail (O17). */
export interface AdminEvidence extends Evidence {
  signedUrl: string | null
}

export interface AdminApprovalEvent {
  decision: "approved" | "rejected" | "suspended" | "reinstated" | "closed"
  documentsSeen: boolean
  note: string | null
  createdAt: string
}

/** X-05: every own-profile field, plus the account email (admin only),
 * the approval history (newest first) and the open report count. */
export interface AdminTutorDetail extends TutorProfile {
  listingState: "draft" | "pending_review" | "listed" | "rejected" | "suspended" | "closed"
  paused: boolean
  indexable: boolean
  submittedAt: string | null
  reviewNote: string | null
  evidence: AdminEvidence[]
  reReviewRequired?: boolean
  accountEmail: string
  history: AdminApprovalEvent[]
  openReports: number
}

/** `POST /api/admin/tutors/{id}/approve` (A3). */
export interface AdminApprove {
  documentsSeen: boolean
  note?: string | null
}

/** Reject, suspend and close bodies (A4, A5, A12). */
export interface AdminNote {
  note?: string | null
}

/** One review text or reply awaiting moderation (X-06); `itemId` is the
 * review id or the reply id, as `kind` says. */
export interface ModerationItem {
  kind: "review" | "reply"
  itemId: string
  text: string
  createdAt: string
  /** First 16 hex characters of the SHA-256 of `text`; send it back on A7. */
  revision: string
}

export interface ModerationPage {
  items: ModerationItem[]
  nextCursor: string | null
}

/** A7 body. `revision` is the one A6 showed with the text: a review text edited
 * since is refused with 409 `text_changed`, never approved unseen (RF-7). */
export interface ReviewModerate {
  decision: "approved" | "rejected"
  revision: string
}

export interface ReplyModerate {
  decision: "approved" | "rejected"
}

export interface AdminReview {
  reviewId: string
  stars: number
  text: string | null
  textState: "none" | "pending" | "approved" | "rejected"
  createdAt: string
}

export interface AdminReply {
  replyId: string
  body: string
  textState: "pending" | "approved" | "rejected"
  createdAt: string
}

/** One row of the X-07 queue, safety concerns first. */
export interface ReportItem {
  reportId: string
  targetType: "tutor_profile" | "review" | "review_reply" | "booking" | "booking_note"
  reason: "safety_concern" | "inappropriate_content" | "harassment" | "spam" | "fake_profile" | "disputed_outcome" | "other"
  state: "open" | "dismissed" | "actioned"
  createdAt: string
}

export interface ReportPage {
  items: ReportItem[]
  nextCursor: string | null
}

/** The booking a booking or note report concerns. No student, no meeting
 * link and no place (SPEC §a.5, O16). */
export interface AdminBookingSummary {
  bookingId: string
  subject: SubjectRef
  mode: TutoringMode
  startsAt: string
  endsAt: string
  effectiveState: EffectiveState
  completedBy: "student" | "parent" | "tutor" | "platform_admin" | null
  notesFrozen: boolean
}

/** X-07 report detail. `notes` is the only admin path to a thread, and each
 * view is logged; hidden note bodies are visible here. */
export interface ReportDetail extends ReportItem {
  reporterParty: "student" | "parent" | "tutor"
  details: string | null
  tutorId: string
  tutorName: string
  snapshot: Record<string, JsonValue>
  bookingSummary: AdminBookingSummary | null
  notes: Note[]
  resolution: ReportResolution | null
  resolutionNote: string | null
  resolvedAt: string | null
}

/** `POST /api/admin/tutoring/reports/{id}/resolve` (A11). */
export interface ReportResolve {
  resolution: ReportResolution
  note?: string | null
}
