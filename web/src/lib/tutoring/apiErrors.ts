import { ApiError } from "@/lib/api"

/*
 * T11 · typed errors for the tutoring API (`docs/tutoring/SPEC.md` §0 "Errors"
 * and the status column of §b.2).
 *
 * The backend refuses with `detail = {"code": "<code>", "message": "<English>"}`
 * (`lemely/web/tutoring_http.py::tutoring_error`; `require_verified_email` sends
 * the code alone). `lib/api.ts` keeps that object on `ApiError.detail`, so a
 * code is read from there and nowhere else.
 *
 * `tutoringErrorOf` turns a failed call into `{ code, status, message }` when
 * the failure is a client error carrying one of the codes below, and into null
 * for everything else: a network failure, a FastAPI validation list, a plain
 * string detail, an unlisted code, a 5xx. The caller then falls back to the
 * generic failure copy (`lib/queryFailure.ts`). The `message` is this file's
 * sentence for the code, not the server's, so a screen's wording does not move
 * when a backend message is reworded.
 *
 * ── Codes ───────────────────────────────────────────────────────────────────
 *
 * `tests/unit/tutoringApiErrors.test.ts` reads every code out of §b.2's status
 * column and fails if one is missing here. The last five are sent by the
 * backend but not spelled out in that column: `email_unverified` (SPEC §0),
 * `no_tutor_profile` (the tutor-route preamble), and `not_found`,
 * `invalid_cursor`, `invalid_area` (`tutoring_http.py`, `deps_tutoring.py`).
 *
 * One code can mean two things on two routes: `access_ended` is the 403 a tutor
 * gets when a student's grant has ended (T20) and the 409 a tutor gets when
 * accepting a booking for a student they have blocked or been blocked by
 * (T11). Use `isAccessEnded` where only the first is meant.
 */

export const TUTORING_ERROR_CODES = [
  // Booking request (SP6)
  "not_linked",
  "not_self",
  "tutor_not_listed",
  "blocked",
  "not_bookable",
  "beyond_horizon",
  "slot_taken",
  "student_busy",
  "already_pending",
  "pending_limit",
  "safety_notice_required",
  "note_not_allowed_for_parent",
  "contact_details_not_allowed",
  "too_many_requests",
  // Booking transitions and notes (S3, S5, S14, T11-T17, PA4, PA5)
  "illegal_transition",
  "cancel_window_closed",
  "notes_closed",
  "outcome_claim_not_open",
  "already_started",
  "meeting_link_not_allowed",
  "reason_required",
  "not_ended",
  "not_requester",
  // Reviews (S6, S7, T18)
  "not_completed",
  "review_not_open_yet",
  "account_too_new",
  "review_exists",
  "edit_window_closed",
  "reply_exists",
  // Tutor profile (T2-T7)
  "profile_exists",
  "tutor_suspended",
  "tutor_closed",
  "incomplete_profile",
  "overlapping_rules",
  "evidence_limit",
  // Grants (T11, T20)
  "access_ended",
  // Reports and admin (R1, A11, A12)
  "report_exists",
  "already_resolved",
  "resolution_not_applicable",
  "already_closed",
  // Sent by the backend, not spelled out in §b.2's status column
  "email_unverified",
  "no_tutor_profile",
  "not_found",
  "invalid_cursor",
  "invalid_area",
] as const

export type TutoringErrorCode = (typeof TUTORING_ERROR_CODES)[number]

/** A refusal the tutoring API made on purpose. */
export interface TutoringError {
  code: TutoringErrorCode
  /** The HTTP status it came with (400 to 499). */
  status: number
  /** One plain sentence a screen can show as it is. */
  message: string
  /** Seconds to wait, from `Retry-After` (429 only). */
  retryAfter?: number
}

/**
 * One sentence per code, in the voice of the rest of the product: plain, no
 * exclamation marks, no prices, no promise about a tutor (SPEC §0 "Copy").
 * `blocked` and `access_ended` stay vague on purpose: neither side learns who
 * ended what (SC-9, SC-11).
 */
export const TUTORING_ERROR_COPY: Readonly<Record<TutoringErrorCode, string>> = {
  not_linked: "This child is not linked to your account.",
  not_self: "You can only book a session for yourself.",
  tutor_not_listed: "This tutor is not taking requests right now.",
  blocked: "You can't do this with this tutor.",
  not_bookable: "This tutor can't be booked for that subject or way of meeting.",
  beyond_horizon: "Sessions can only be booked up to 28 days ahead.",
  slot_taken: "That time was just taken. Choose another.",
  student_busy: "There is already a session at that time.",
  already_pending: "There is already a request waiting for this tutor.",
  pending_limit: "There are too many requests waiting for a reply. Wait for one before sending another.",
  safety_notice_required: "Read the safety notice before you continue.",
  note_not_allowed_for_parent: "Only the student can add a first note.",
  contact_details_not_allowed: "Phone numbers, email addresses and chat handles can't go here.",
  too_many_requests: "That is happening too often. Try again in a little while.",
  illegal_transition: "This booking has already moved on, so that is no longer possible.",
  cancel_window_closed: "It is too close to the start time to cancel this session.",
  notes_closed: "Notes on this booking are closed.",
  outcome_claim_not_open: "This session can't be marked as complete yet.",
  already_started: "This session has already started.",
  meeting_link_not_allowed: "That meeting link isn't allowed.",
  reason_required: "Add a reason. Cancelling this close to the start needs one.",
  not_ended: "You can do this once the session has ended.",
  not_requester: "Only the person who made the booking can do this.",
  not_completed: "A session can be reviewed once it has been completed.",
  review_not_open_yet: "Reviews open seven days after a session ends.",
  account_too_new: "An account needs to be a little older before it can leave a review.",
  review_exists: "This session already has a review.",
  edit_window_closed: "This review can no longer be edited.",
  reply_exists: "You have already replied to this review.",
  profile_exists: "You already have a tutor profile.",
  tutor_suspended: "Your tutor profile is suspended.",
  tutor_closed: "Your tutor profile is closed.",
  incomplete_profile: "Finish the required parts of your profile before you submit it.",
  overlapping_rules: "Some of your weekly availability times overlap.",
  evidence_limit: "You can upload up to five files. Delete one to add another.",
  access_ended: "You no longer have access to this.",
  report_exists: "You have already reported this.",
  already_resolved: "This report has already been resolved.",
  resolution_not_applicable: "That resolution does not apply to this report.",
  already_closed: "This tutor is already closed.",
  email_unverified: "Confirm your email address to continue.",
  no_tutor_profile: "You don't have a tutor profile yet.",
  not_found: "We couldn't find that.",
  invalid_cursor: "That page link is no longer valid. Reload the list.",
  invalid_area: "Choose an area from the list.",
}

const KNOWN: ReadonlySet<string> = new Set(TUTORING_ERROR_CODES)

function isKnownCode(value: string): value is TutoringErrorCode {
  return KNOWN.has(value)
}

/** The `code` in an error's `detail` object, when `detail` is one. */
function codeOfDetail(detail: unknown): string | null {
  if (detail === null || typeof detail !== "object" || Array.isArray(detail)) return null
  const code = (detail as { code?: unknown }).code
  return typeof code === "string" ? code : null
}

/**
 * The typed refusal behind a failed tutoring call, or null when the failure is
 * not one: not an `ApiError`, not a 4xx, a `detail` that is not an object with a
 * string `code` (FastAPI's validation list is an array), or a code outside the
 * list above.
 */
export function tutoringErrorOf(error: unknown): TutoringError | null {
  if (!(error instanceof ApiError)) return null
  if (error.status < 400 || error.status > 499) return null
  const code = codeOfDetail(error.detail)
  if (code === null || !isKnownCode(code)) return null
  const typed: TutoringError = { code, status: error.status, message: TUTORING_ERROR_COPY[code] }
  if (error.retryAfter !== undefined) typed.retryAfter = error.retryAfter
  return typed
}

/** Whether `error` is the tutoring refusal `code`, on any route. */
export function isTutoringError(error: unknown, code: TutoringErrorCode): boolean {
  return tutoringErrorOf(error)?.code === code
}

/**
 * T20's 403: a grant existed for this tutor and student and is not valid now.
 * Deliberately not true for the 409 `access_ended` of an accept (T11).
 */
export function isAccessEnded(error: unknown): boolean {
  const typed = tutoringErrorOf(error)
  return typed?.code === "access_ended" && typed.status === 403
}
