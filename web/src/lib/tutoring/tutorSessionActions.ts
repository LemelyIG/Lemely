/*
 * T-18 · what a tutor can do with one session, and the forms behind it (SPEC §d,
 * §a.3, rows 18 and 16).
 *
 * **Actions come from the API.** `Booking.allowedActions` is computed per viewer
 * from the booking's effective state, the clock, blocks and the tutor's own
 * standing (SPEC §i.4). The screen shows a control only for an action in that
 * list and never works one out from times, so `tutorActions` is a filter and an
 * ordering, nothing more. `review` and `post_note` are in the list for other
 * viewers and are not tutor controls: a note's composer is the notes thread's
 * own business (`NotesPage.canPost`).
 *
 * **Late cancel.** `cancel_with_reason` means the tutor is cancelling an
 * accepted session inside 24 hours of its start. The server then requires a
 * reason (422 `reason_required`) and shows it to the student and linked parents;
 * the sheet collects it and will not send a blank one. `cancel` and
 * `cancel_with_reason` never arrive together; if both did, the stricter wins.
 *
 * **Meeting link.** `meetingLinkError` is a client mirror of
 * `core.contact_patterns.meeting_link_allowed`, so a bad link is caught before
 * the request and explained next to the field. The host list is compared with
 * the Python module by `tutorSessionActions.test.ts`. The server stays
 * authoritative: it answers 422 `meeting_link_not_allowed`, which the screen
 * shows too.
 *
 * **The accept form asks only for what the mode keeps** (SPEC §i.4): a link for
 * a virtual session, a place for an in-person one, nothing for "other".
 *
 * **A tutor never learns that a parent link exists** (SC-9): whoever made the
 * request, the screen says "the student".
 */

import { ApiError } from "@/lib/api"
import { isTutoringError, tutoringErrorOf } from "@/lib/tutoring/apiErrors"
import type { ListingState } from "@/lib/tutoring/profileSteps"
import { CONTACT_DETAILS_MESSAGE } from "@/lib/tutoring/safetyNoticeCopy"
import { describeQueryFailure } from "@/lib/queryFailure"
import type { Booking, BookingAccept, BookingReason, TutoringMode, ViewerAction } from "@/lib/tutoringTypes"

// ── Actions ─────────────────────────────────────────────────────────────────

export type TutorAction = "accept" | "decline" | "cancel" | "cancel_with_reason" | "complete" | "no_show"

/** The controls a tutor can have, in the order the screen lays them out. */
export const TUTOR_ACTIONS: readonly TutorAction[] = [
  "accept",
  "decline",
  "complete",
  "no_show",
  "cancel",
  "cancel_with_reason",
]

/** The controls to draw for a booking: only what the API allowed, in a fixed order, one cancel at most. */
export function tutorActions(allowed: readonly ViewerAction[]): TutorAction[] {
  const permitted = new Set<ViewerAction>(allowed)
  const controls = TUTOR_ACTIONS.filter((action) => permitted.has(action))
  // The two cancels are exclusive (SPEC §b.3). If a payload carried both, the one
  // that asks for a reason is the safe one to show.
  return controls.includes("cancel_with_reason") ? controls.filter((a) => a !== "cancel") : controls
}

export function cancelRequiresReason(allowed: readonly ViewerAction[]): boolean {
  return allowed.includes("cancel_with_reason")
}

// ── Which sessions the home draws ───────────────────────────────────────────

export interface SessionQueuesView {
  /** Draw the three queues (requests, upcoming, waiting for an outcome). */
  show: boolean
  /** A line to show instead of, or above, the queues; null when none is needed. */
  note: string | null
}

/**
 * T-15: what to draw under the listing banner for a profile in `state`.
 *
 * A profile that exists and has been through review can hold requests, accepted
 * sessions and sessions awaiting an outcome whatever state it is in now: a
 * rejection cancels nothing (SPEC §a.3), and those students, often minors, are
 * still waiting. So the queues are drawn for every state but `draft`, which has
 * never been listed and so cannot have a booking. Which buttons a row gets is
 * `Booking.allowedActions`, which already drops the write actions for a
 * suspended or closed profile (the server answers 409 to them anyway).
 */
export function sessionQueuesView(state: ListingState): SessionQueuesView {
  switch (state) {
    case "draft":
      return { show: false, note: "Requests and sessions will appear here once your profile is listed." }
    case "suspended":
      return { show: true, note: "Your profile is suspended, so you can't act on these requests and sessions." }
    case "closed":
      return { show: true, note: "Your profile is closed, so you can't act on these requests and sessions." }
    default:
      return { show: true, note: null }
  }
}

/**
 * A 422 `reason_required` from a plain cancel means the 24-hour line passed
 * after the page loaded: the reason sheet is the next step, not an error.
 */
export function lateCancelNeeded(error: unknown): boolean {
  return isTutoringError(error, "reason_required")
}

/**
 * A 409 or 422 on an action means the booking changed under the page (the 24-hour
 * line, a start time, a block, another viewer's action), so the cached booking is
 * stale and the buttons drawn from it may be wrong. Reload it.
 */
export function shouldRefetchBooking(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 409 || error.status === 422)
}

// ── Cancel and decline ──────────────────────────────────────────────────────

/** SPEC T-18: the sentence above the reason box of the late-cancel sheet. */
export const LATE_CANCEL_NOTICE =
  "You're cancelling less than 24 hours before the start. The student and any parents linked to their account will see your reason."

/** `booking_repo.MAX_REASON_LENGTH`. */
export const CANCEL_REASON_MAX = 300

function chars(value: string): number {
  return [...value].length
}

/** Length in code points, the unit `validateCancelReason` and the server's limit use. */
export function reasonLength(value: string): number {
  return chars(value)
}

/** An error sentence for a reason that cannot be sent, or null. */
export function validateCancelReason(reason: string, required: boolean): string | null {
  const text = reason.trim()
  if (required && text === "") {
    return "Add a reason. The student will read it, so say what happened in a sentence or two."
  }
  if (chars(text) > CANCEL_REASON_MAX) {
    return `Shorten the reason to ${CANCEL_REASON_MAX} characters or fewer.`
  }
  return null
}

/** Body of a cancel: the trimmed reason, or no reason at all when an ordinary cancel has none. */
export function cancelBody(reason: string, _required: boolean): BookingReason {
  const text = reason.trim()
  return text === "" ? {} : { reason: text }
}

export function declineBody(reason: string): BookingReason {
  return cancelBody(reason, false)
}

// ── Meeting link ────────────────────────────────────────────────────────────

/** `core.contact_patterns.MEETING_HOSTS`: a link must point at one of these or a subdomain. */
export const MEETING_HOSTS: readonly string[] = [
  "meet.google.com",
  "zoom.us",
  "teams.microsoft.com",
  "teams.live.com",
  "whereby.com",
]

/** The services as people know them, for the sentence that lists what is allowed. */
export const ACCEPT_SERVICES: readonly string[] = ["Google Meet", "Zoom", "Microsoft Teams", "Whereby"]

/** `_MAX_LINK_LENGTH` in `core.contact_patterns` (the column is varchar(500)). */
const MAX_LINK_LENGTH = 500
/** `booking_repo.MAX_LOCATION_LENGTH`. */
export const LOCATION_MAX = 300

const HOST = /^[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+$/

const LINK_HELP = `Use a link from ${ACCEPT_SERVICES.slice(0, -1).join(", ")} or ${ACCEPT_SERVICES.at(-1)}, starting with https://.`

function isPlainAscii(value: string): boolean {
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0
    // Printable ASCII only; no space (0x20), no DEL, no control, no backslash.
    if (code < 0x21 || code > 0x7e || char === "\\") return false
  }
  return true
}

/**
 * A sentence for a meeting link that cannot be used, or null for one that can.
 * Mirrors `meeting_link_allowed`: https only, no userinfo, no port or 443, a host
 * that is an allowed host or a subdomain of one, plain ASCII, at most 500 characters.
 */
export function meetingLinkError(value: string): string | null {
  const link = value.trim()
  if (link === "") return `Add the meeting link. ${LINK_HELP}`
  if (link.length > MAX_LINK_LENGTH || !isPlainAscii(link)) return `That link can't be used. ${LINK_HELP}`
  const match = /^([A-Za-z][A-Za-z0-9+.-]*):\/\/([^/?#]*)/.exec(link)
  if (!match) return `That isn't a full link. ${LINK_HELP}`
  if (match[1].toLowerCase() !== "https") return `The link has to start with https://. ${LINK_HELP}`
  const netloc = match[2]
  if (netloc === "" || netloc.includes("@")) return `That link can't be used. ${LINK_HELP}`
  const colon = netloc.indexOf(":")
  const host = (colon === -1 ? netloc : netloc.slice(0, colon)).toLowerCase()
  const port = colon === -1 ? "" : netloc.slice(colon + 1)
  if (colon !== -1 && port !== "443") return `That link can't be used. ${LINK_HELP}`
  if (!HOST.test(host)) return `That link can't be used. ${LINK_HELP}`
  const allowed = MEETING_HOSTS.some((h) => host === h || host.endsWith(`.${h}`))
  return allowed ? null : `That service isn't allowed. ${LINK_HELP}`
}

// ── Accept ──────────────────────────────────────────────────────────────────

export type AcceptDetail = "link" | "place" | "none"

export function acceptDetailFor(mode: TutoringMode): AcceptDetail {
  if (mode === "virtual") return "link"
  if (mode === "in_person") return "place"
  return "none"
}

export interface AcceptValues {
  meetingLink: string
  locationDetail: string
}

export type AcceptErrors = Partial<Record<keyof AcceptValues, string>>

export function validateAccept(mode: TutoringMode, values: AcceptValues): AcceptErrors {
  const detail = acceptDetailFor(mode)
  if (detail === "link") {
    const error = meetingLinkError(values.meetingLink)
    return error ? { meetingLink: error } : {}
  }
  if (detail === "place") {
    const place = values.locationDetail.trim()
    if (place === "") return { locationDetail: "Add where the session will take place." }
    if (chars(place) > LOCATION_MAX) {
      return { locationDetail: `Shorten the place to ${LOCATION_MAX} characters or fewer.` }
    }
  }
  return {}
}

/** Body of an accept: only the detail the mode keeps, trimmed. */
export function acceptBody(mode: TutoringMode, values: AcceptValues): BookingAccept {
  const detail = acceptDetailFor(mode)
  if (detail === "link") return { meetingLink: values.meetingLink.trim() }
  if (detail === "place") return { locationDetail: values.locationDetail.trim() }
  return {}
}

// ── Who asked, and why notes may be closed ──────────────────────────────────

/** Whoever made the request, a tutor reads "the student" (SC-9). */
export function requestedByLabel(_requestedBy: string): string {
  return "the student"
}

type OutcomeFacts = Pick<
  Booking,
  "effectiveState" | "cancelledBy" | "cancelledLate" | "cancelReason" | "declineReason" | "completedBy"
>

/**
 * One sentence on how a session ended, for the tutor, or null while it is live.
 * A parent is read as the student, and a platform admin and the system read the
 * same ("Lemely"), so a tutor can tell neither a parent link nor a block from a
 * cancellation (SC-9, SC-11). Reasons are plain text.
 */
export function sessionOutcomeLine(booking: OutcomeFacts): string | null {
  switch (booking.effectiveState) {
    case "declined":
      return booking.declineReason ? `You declined this request. Your reason: ${booking.declineReason}` : "You declined this request."
    case "expired":
      return "This request lapsed because its start time passed before you replied."
    case "cancelled": {
      if (booking.cancelledBy === "tutor") {
        return booking.cancelledLate && booking.cancelReason
          ? `You cancelled this session less than 24 hours before the start. Your reason: ${booking.cancelReason}`
          : "You cancelled this session."
      }
      if (booking.cancelledBy === "student" || booking.cancelledBy === "parent") {
        return "The student cancelled this session."
      }
      return "This session was cancelled by Lemely."
    }
    case "completed":
      if (booking.completedBy === "tutor") return "You recorded this session as completed."
      if (booking.completedBy === "student" || booking.completedBy === "parent") {
        return "The student marked this session as completed."
      }
      if (booking.completedBy === "platform_admin") return "Lemely marked this session as completed."
      return "This session is completed."
    case "no_show":
      return "You marked this student as a no-show."
    case "awaiting_outcome":
      return "This session has ended. Record what happened."
    default:
      return null
  }
}

export interface NotesFreezeInput {
  /** `Booking.notesFrozen`. */
  notesFrozen: boolean
  /** `Booking.student.studentId`. */
  studentId: string
  /** The student ids this tutor has blocked (B1 `counterpartId`), or null if the list could not be read. */
  blockedStudentIds: readonly string[] | null
}

export interface NotesFreezeView {
  /** Pass to the notes thread as `frozen`: draws "Notes are paused while Lemely looks at a report." */
  frozen: boolean
  /** The freeze is the tutor's own block, so the screen words it itself. */
  ownBlock: boolean
}

/**
 * A tutor who blocked a student also reads `notesFrozen: true` (SPEC §i.8), and
 * the report line would be wrong for them: no report is open. The tutor knows
 * their own blocks (B1), so when the student is one of them the screen says so
 * instead. When the block list could not be read the plain freeze line stands.
 */
export function notesFreezeView({ notesFrozen, studentId, blockedStudentIds }: NotesFreezeInput): NotesFreezeView {
  if (!notesFrozen) return { frozen: false, ownBlock: false }
  if (blockedStudentIds?.includes(studentId)) return { frozen: false, ownBlock: true }
  return { frozen: true, ownBlock: false }
}

/** Under the thread when the freeze is the tutor's own block. */
export const OWN_BLOCK_NOTES_LINE =
  "You blocked this student, so new notes are closed. You can still read the notes and report them."

// ── Failure sentences ───────────────────────────────────────────────────────

/** Why a tutoring screen could not load: the API's own sentence for a refusal it sent on purpose, else the shared one. */
export function tutorLoadFailureMessage(error: unknown): string {
  return tutoringErrorOf(error)?.message ?? describeQueryFailure(error)
}

/**
 * Why a save or an action did not go through. A refused contact detail uses the
 * SPEC §d sentence; any other refusal the API sent on purpose uses its own
 * sentence; anything else says plainly that it did not go through.
 */
export function tutorActionFailureMessage(error: unknown, fallback: string): string | null {
  if (error === null || error === undefined) return null
  const typed = tutoringErrorOf(error)
  if (typed?.code === "contact_details_not_allowed") return CONTACT_DETAILS_MESSAGE
  return typed?.message ?? fallback
}
