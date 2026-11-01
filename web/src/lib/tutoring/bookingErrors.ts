import { ApiError } from "@/lib/api"
import {
  TUTORING_ERROR_COPY,
  tutoringErrorOf,
  type TutoringErrorCode,
} from "@/lib/tutoring/apiErrors"
import { CONTACT_DETAILS_MESSAGE } from "@/lib/tutoring/safetyNoticeCopy"

/*
 * T22 · what a refused booking request (SP6), or a refused tutor page (SP2),
 * says and what the screen does next (`docs/tutoring/SPEC.md` §b.2 SP6, §d
 * S-34 and S-35).
 *
 * T11's `apiErrors.ts` is the only table of codes. This file adds nothing to
 * that table: it takes a `TutoringErrorCode` and says, for the booking screens,
 *
 *   - the sentence. S-35 fixes the wording of six refusals; those sentences are
 *     here, and `tutoringBookingErrors.test.ts` reads them out of the SPEC. Every
 *     other code keeps T11's own sentence (`TUTORING_ERROR_COPY`), so a code the
 *     SPEC gives no words for is never left without any.
 *   - the next step, as an `action` the screen understands, and the `field` the
 *     message belongs to, so a refused note is shown on the note.
 *
 * `BOOKING_REFUSALS` is the handling of the codes SP6 can send (the test
 * compares its keys with the SP6 row of the SPEC, and `satisfies` ties every key
 * to T11's union). Any other code still gets an answer from `bookingRefusalFor`.
 *
 * ── A hidden tutor is one answer ────────────────────────────────────────────
 *
 * An unlisted, paused, suspended, closed, unknown or blocked tutor is the same
 * 404 for a student (SPEC §i.7), so a student never learns a tutor blocked
 * them. Here `not_found`, `tutor_not_listed` and `blocked` all read S-34's
 * "This tutor isn't taking bookings right now." and none of them mentions a
 * block. A 404 with no recognised code is the same answer (`isTutorHidden`).
 */

/** S-34 "Not listed". The answer for every tutor the student cannot see. */
export const TUTOR_UNAVAILABLE_MESSAGE = "This tutor isn't taking bookings right now."

/** What the booking screen does about a refusal. */
export type BookingRefusalAction =
  /** Nothing beyond showing the sentence. */
  | "none"
  /** Fetch the slots again and drop the chosen time (`slot_taken`). */
  | "refresh_slots"
  /** Keep the form, ask for a different time. */
  | "choose_another_time"
  /** Offer a link to the waiting request. */
  | "open_requests"
  /** Offer the link to confirm the email address. */
  | "verify_email"
  /** Open the safety notice (C-24) again; the server counted it unseen. */
  | "show_safety_notice"
  /** The tutor is gone for this reader: show the "not listed" state. */
  | "tutor_unavailable"

/** Which part of the form the sentence belongs to. */
export type BookingRefusalField = "slot" | "note" | "child" | "form"

export interface BookingRefusal {
  code: TutoringErrorCode
  /** The HTTP status it came with; absent when built from a code alone. */
  status?: number
  message: string
  action: BookingRefusalAction
  field: BookingRefusalField | null
  /** Seconds to wait, from `Retry-After` (429 only). */
  retryAfter?: number
}

interface Handling {
  action: BookingRefusalAction
  field: BookingRefusalField | null
  /** S-34 / S-35 / §d wording, where the SPEC fixes one. Omitted: T11's sentence. */
  message?: string
}

/**
 * The codes SP6 can send, SP2's `email_unverified`, and the hidden-tutor 404,
 * each with what the screen does. Keys are T11 codes (`satisfies` rejects any
 * other); the SPEC test fails if the SP6 row names a code that is missing.
 */
export const BOOKING_REFUSALS = {
  // 403
  not_linked: { action: "none", field: "child" },
  not_self: { action: "none", field: "child" },
  email_unverified: {
    action: "verify_email",
    field: null,
    message: "Verify your email to book a session.",
  },
  // 404, and the codes a tutor's own routes send for the same hidden tutor
  not_found: { action: "tutor_unavailable", field: null, message: TUTOR_UNAVAILABLE_MESSAGE },
  tutor_not_listed: { action: "tutor_unavailable", field: null, message: TUTOR_UNAVAILABLE_MESSAGE },
  blocked: { action: "tutor_unavailable", field: null, message: TUTOR_UNAVAILABLE_MESSAGE },
  // 409
  not_bookable: { action: "none", field: "form" },
  beyond_horizon: { action: "refresh_slots", field: "slot" },
  slot_taken: {
    action: "refresh_slots",
    field: "slot",
    message: "Someone just requested that time. Pick another.",
  },
  student_busy: {
    action: "choose_another_time",
    field: "slot",
    message: "You already have a session then.",
  },
  already_pending: { action: "open_requests", field: null },
  pending_limit: {
    action: "none",
    field: null,
    message: "You have 5 requests waiting. Cancel one or wait for replies.",
  },
  safety_notice_required: { action: "show_safety_notice", field: null },
  // 422
  note_not_allowed_for_parent: { action: "none", field: "note" },
  contact_details_not_allowed: { action: "none", field: "note", message: CONTACT_DETAILS_MESSAGE },
  text_too_long: { action: "none", field: "note" },
  student_required: { action: "none", field: "child" },
  invalid_starts_at: { action: "refresh_slots", field: "slot" },
  invalid_window: { action: "refresh_slots", field: "slot" },
  invalid_duration: { action: "none", field: "form" },
  // 429
  too_many_requests: {
    action: "none",
    field: null,
    message: "You've made a lot of requests today. Try again tomorrow.",
  },
} as const satisfies Partial<Record<TutoringErrorCode, Handling>>

const HANDLING: Partial<Record<TutoringErrorCode, Handling>> = BOOKING_REFUSALS

/**
 * The refusal for a code. Total over T11's union: a code without handling of
 * its own keeps T11's sentence, takes no action and belongs to no field.
 */
export function bookingRefusalFor(code: TutoringErrorCode, status?: number): BookingRefusal {
  const handling = HANDLING[code]
  const refusal: BookingRefusal = {
    code,
    message: handling?.message ?? TUTORING_ERROR_COPY[code],
    action: handling?.action ?? "none",
    field: handling?.field ?? null,
  }
  if (status !== undefined) refusal.status = status
  return refusal
}

/** A 404 from a tutor page or SP5 and SP6: the same answer whatever hid the tutor. */
export function isTutorHidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

/**
 * The refusal behind a failed booking or tutor-page call, or null when the
 * failure is not one the API made on purpose (a network failure, a 5xx, a code
 * nobody defined): the screen then shows its generic failure copy. A 404 is
 * always the hidden-tutor answer, with or without a recognised body.
 */
export function bookingRefusalOf(error: unknown): BookingRefusal | null {
  if (isTutorHidden(error)) return bookingRefusalFor("not_found", 404)
  const typed = tutoringErrorOf(error)
  if (typed === null) return null
  const refusal = bookingRefusalFor(typed.code, typed.status)
  if (typed.retryAfter !== undefined) refusal.retryAfter = typed.retryAfter
  return refusal
}

/**
 * Whether a refusal should still be on the screen. "Read the safety notice
 * before you continue" only says why the notice sheet opened; once the student
 * has acknowledged it (`safetyNoticeOpen === false`) the sentence is stale and
 * the next press of "Send request" starts clean. A screen that does not say
 * whether the sheet is open (`undefined`) keeps every refusal.
 */
export function refusalIsCurrent(refusal: BookingRefusal, safetyNoticeOpen: boolean | undefined): boolean {
  return !(refusal.action === "show_safety_notice" && safetyNoticeOpen === false)
}

/** Which of the form's two free-text notes a refused note belongs to. */
export interface NoteFieldTargets {
  /** The student's first note. */
  first: boolean
  /** The "How would you like to meet?" note of the Other way of meeting. */
  other: boolean
}

/**
 * The server refuses "the note" without saying which text it read, so the
 * sentence goes on every note field that holds text: one when one is filled,
 * both when both are. A field the request does not carry (a parent has no first
 * note; the other-mode note is only sent for mode `other`) never counts. With
 * nothing typed, the one field the reader can see.
 */
export function noteFieldTargets(input: {
  audience: "student" | "parent"
  firstNote: string
  mode: string
  otherNote: string
}): NoteFieldTargets {
  const first = input.audience === "student" && input.firstNote.trim() !== ""
  const other = input.mode === "other" && input.otherNote.trim() !== ""
  if (first || other) return { first, other }
  return input.audience === "student" ? { first: true, other: false } : { first: false, other: true }
}
