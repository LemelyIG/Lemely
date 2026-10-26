import type {
  EffectiveState,
  ReportItem,
  TutorOwnProfile,
  TutoringMode,
} from "@/lib/tutoringTypes"

/*
 * T11 · react-query keys for the tutoring marketplace (`docs/tutoring/SPEC.md`
 * §b.2). One factory per GET route, plus `…Scope` prefixes for invalidation.
 *
 * ── Every key starts with "tutoring", and none is on the persist allowlist ──
 *
 * Tutoring responses are `private, no-store` (SPEC §b.5, SC-26): a booking
 * carries a meeting link, a grant says who may read a child's marks. They must
 * never be written to IndexedDB, so no key here may match a prefix in
 * `lib/offline/persistAllowlist.ts`, and the allowlist must never gain one
 * that starts "tutoring". `tests/unit/persistAllowlist.test.ts` enforces both
 * halves; `tests/unit/tutoringQueryKeys.test.ts` enforces that every GET hook
 * takes its key from this file.
 *
 * ── Shape ───────────────────────────────────────────────────────────────────
 *
 *   ["tutoring", "public", …]                     P1-P3, no auth
 *   ["tutoring", "directory", …]  ["tutoring", "tutors", id, …]   SP1-SP5
 *   ["tutoring", "student", …]                    S1-S16
 *   ["tutoring", "own", …]                        T1-T21, the caller's own tutor side
 *   ["tutoring", "parent", childId, …]            PA1-PA7
 *   ["tutoring", "blocks"]                        B1
 *   ["tutoring", "admin", …]                      A1-A10
 *
 * Lists carry their params object (`when`, `cursor`, filters) as the last
 * segment so two filters never share an entry; `undefined` members drop out of
 * react-query's key hash, so `{}` and `{ cursor: undefined }` are one entry.
 */

export const TUTORING_ROOT = "tutoring"

// ── Request parameters (query string) ───────────────────────────────────────

/** Every cursor-paged list takes these (SPEC §0 "Paging"). */
export interface PageParams {
  cursor?: string | null
  limit?: number
}

export type TimeOfDay = "morning" | "afternoon" | "evening"

/** P1: `mode` repeats (OR); `minRating` is 1.0 to 5.0 in steps of 0.5. */
export interface PublicDirectoryParams extends PageParams {
  subject?: string
  mode?: TutoringMode[]
  area?: string
  minRating?: number
}

/** SP1: P1's filters plus "usually available" (`day` 1-7, `timeOfDay`). */
export interface DirectoryParams extends PublicDirectoryParams {
  day?: number[]
  timeOfDay?: TimeOfDay[]
}

/** SP5: `from` is a tutor-zone date, `days` 1-28 (default 14). */
export interface SlotsParams {
  from: string
  days?: number
  durationMinutes: 45 | 60 | 90 | 120
}

export type BookingWhen = "upcoming" | "past"

/** S1, PA1. */
export interface BookingsParams extends PageParams {
  when: BookingWhen
}

/** T9: `state` is an effective state, filtered server-side. */
export interface TutorBookingsParams extends BookingsParams {
  state?: EffectiveState
}

/** S11, PA7. */
export interface AccessLogParams extends PageParams {
  tutorId?: string
}

/** A1: the listing state to show (server default `pending_review`). */
export type AdminTutorState = TutorOwnProfile["listingState"]

export interface AdminTutorsParams extends PageParams {
  state?: AdminTutorState
}

/** A6. */
export interface ModerationParams extends PageParams {
  kind?: "review" | "reply" | "all"
}

/** A9: the report state to show (server default open). */
export interface AdminReportsParams extends PageParams {
  state?: ReportItem["state"]
}

// ── Keys ────────────────────────────────────────────────────────────────────

const R = TUTORING_ROOT

export const tutoringKeys = {
  /** Everything tutoring: cleared wholesale on sign-out if a screen ever needs it. */
  all: [R] as const,

  // Public (P1-P3)
  publicTutors: (params: PublicDirectoryParams) => [R, "public", "tutors", params] as const,
  publicTutor: (tutorId: string) => [R, "public", "tutor", tutorId] as const,
  publicAreas: () => [R, "public", "areas"] as const,

  // Logged-in directory (SP1-SP5)
  /** A block changes who the directory shows. */
  directoryScope: () => [R, "directory"] as const,
  directoryTutors: (params: DirectoryParams) => [R, "directory", params] as const,
  tutorProfile: (tutorId: string) => [R, "tutors", tutorId, "profile"] as const,
  tutorReviews: (tutorId: string, params: PageParams) =>
    [R, "tutors", tutorId, "reviews", params] as const,
  tutorOutcomes: (tutorId: string) => [R, "tutors", tutorId, "outcomes"] as const,
  tutorSlots: (tutorId: string, params: SlotsParams) =>
    [R, "tutors", tutorId, "slots", params] as const,
  /** A new booking changes this tutor's open slots. */
  tutorSlotsScope: (tutorId: string) => [R, "tutors", tutorId, "slots"] as const,

  // Student (S1-S16)
  studentBookingsScope: () => [R, "student", "bookings"] as const,
  studentBookings: (params: BookingsParams) =>
    [R, "student", "bookings", "list", params] as const,
  studentBooking: (bookingId: string) => [R, "student", "bookings", "detail", bookingId] as const,
  studentBookingNotesScope: (bookingId: string) =>
    [R, "student", "bookings", "notes", bookingId] as const,
  studentBookingNotes: (bookingId: string, params: PageParams) =>
    [R, "student", "bookings", "notes", bookingId, params] as const,
  studentGrants: () => [R, "student", "grants"] as const,
  studentAccessLog: (params: AccessLogParams) => [R, "student", "access-log", params] as const,
  studentSettings: () => [R, "student", "settings"] as const,
  studentClassAccess: () => [R, "student", "class-access"] as const,

  // The caller's own tutor side (T1-T21)
  ownProfile: () => [R, "own", "profile"] as const,
  ownPreview: () => [R, "own", "preview"] as const,
  ownBookingsScope: () => [R, "own", "bookings"] as const,
  tutorBookings: (params: TutorBookingsParams) =>
    [R, "own", "bookings", "list", params] as const,
  tutorBooking: (bookingId: string) => [R, "own", "bookings", "detail", bookingId] as const,
  tutorBookingNotesScope: (bookingId: string) =>
    [R, "own", "bookings", "notes", bookingId] as const,
  tutorBookingNotes: (bookingId: string, params: PageParams) =>
    [R, "own", "bookings", "notes", bookingId, params] as const,
  ownReviewsScope: () => [R, "own", "reviews"] as const,
  ownReviews: (params: PageParams) => [R, "own", "reviews", params] as const,
  tutorStudentsScope: () => [R, "own", "students"] as const,
  tutorStudents: (params: PageParams) => [R, "own", "students", "list", params] as const,
  /** T20. The one entry a 403 `access_ended` removes (see `useTutoringApi`). */
  tutorStudent: (studentId: string) => [R, "own", "students", "detail", studentId] as const,

  // Parent (PA1-PA7)
  parentChildScope: (childId: string) => [R, "parent", childId] as const,
  parentBookingsScope: (childId: string) => [R, "parent", childId, "bookings"] as const,
  parentBookings: (childId: string, params: BookingsParams) =>
    [R, "parent", childId, "bookings", "list", params] as const,
  parentBooking: (childId: string, bookingId: string) =>
    [R, "parent", childId, "bookings", "detail", bookingId] as const,
  parentBookingNotesScope: (childId: string, bookingId: string) =>
    [R, "parent", childId, "bookings", "notes", bookingId] as const,
  parentBookingNotes: (childId: string, bookingId: string, params: PageParams) =>
    [R, "parent", childId, "bookings", "notes", bookingId, params] as const,
  parentGrants: (childId: string) => [R, "parent", childId, "grants"] as const,
  parentAccessLog: (childId: string, params: AccessLogParams) =>
    [R, "parent", childId, "access-log", params] as const,

  // Safety (B1)
  blocks: () => [R, "blocks"] as const,

  // Platform admin (A1-A10)
  adminTutorsScope: () => [R, "admin", "tutors"] as const,
  adminTutors: (params: AdminTutorsParams) => [R, "admin", "tutors", "list", params] as const,
  adminTutor: (tutorId: string) => [R, "admin", "tutors", "detail", tutorId] as const,
  adminModerationScope: () => [R, "admin", "moderation"] as const,
  adminModeration: (params: ModerationParams) => [R, "admin", "moderation", params] as const,
  adminReportListScope: () => [R, "admin", "reports", "list"] as const,
  adminReports: (params: AdminReportsParams) => [R, "admin", "reports", "list", params] as const,
  adminReport: (reportId: string) => [R, "admin", "reports", "detail", reportId] as const,
}

/** The student id in a T20 detail key, or null for any other key. */
export function studentIdOfDetailKey(key: readonly unknown[]): string | null {
  const prefix = tutoringKeys.tutorStudent("")
  if (key.length !== prefix.length) return null
  for (let i = 0; i < prefix.length - 1; i++) {
    if (key[i] !== prefix[i]) return null
  }
  const id = key[prefix.length - 1]
  return typeof id === "string" && id.length > 0 ? id : null
}
