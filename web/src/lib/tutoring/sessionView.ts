/*
 * T23 · what S-36 (My sessions) and S-37 (Session detail) say and offer, as pure
 * functions (SPEC §d, §a.3, §i.8). The components only draw what is decided
 * here, so the rules run in the node-only test runner.
 *
 * ── Four rules this module keeps ────────────────────────────────────────────
 *
 * 1. Controls come from `Booking.allowedActions` and from nothing else. A
 *    session's state never turns a button on (`sessionActions`); a tutor-only
 *    action (`accept`, `decline`, `no_show`, `cancel_with_reason`) is ignored
 *    here whatever the API sends. A parent acts only on a booking they asked
 *    for (SPEC §d P-06), and never reviews.
 * 2. Words someone else wrote (`cancelReason`, `declineReason`, a place, a
 *    link, a class name) are returned exactly as given and drawn as text. This
 *    module never escapes, strips or parses them, and no component here
 *    renders HTML (SC-7).
 * 3. A system cancellation reads as the platform, in one fixed sentence. The
 *    stored reason is not repeated, and no sentence here says who blocked whom
 *    or why a booking was cancelled by the system (SC-11, SPEC §i.8).
 * 4. Times are the tutor's, with the zone label, for every viewer. The API
 *    does not put a zone on a booking; v1 has one zone (SPEC §0 "Times": weekly
 *    rules are Cairo wall clock), named once below and overridable per call.
 *
 * Every fixed sentence is copied from the SPEC; `tutoringSessionView.test.ts`
 * parses them out of it.
 */

import { useMemo, useState } from "react"
import type { UseQueryResult } from "@tanstack/react-query"
import type {
  Booking,
  EffectiveState,
  MyReview,
  ReviewCreate,
  ReviewUpdate,
  TutoringMode,
} from "@/lib/tutoringTypes"
import { tutoringErrorOf } from "./apiErrors"
import { bookingStatusOf } from "./bookingStatus"
import { CONTACT_DETAILS_MESSAGE } from "./safetyNoticeCopy"
import { formatSlotRange } from "./slotGroups"

// ── Zone and dates ─────────────────────────────────────────────────────────

export const SESSION_ZONE = "Africa/Cairo"
export const SESSION_ZONE_LABEL = "Cairo time"

export type SessionViewer = "student" | "parent"

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const

const dateFormatters = new Map<string, Intl.DateTimeFormat>()

/** "8 Jan 2026": the calendar date in the tutor's zone, so an evening instant is not the next UTC day. */
export function formatTutorDate(iso: string, zone: string = SESSION_ZONE): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ""
  let formatter = dateFormatters.get(zone)
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", { timeZone: zone, year: "numeric", month: "numeric", day: "numeric" })
    dateFormatters.set(zone, formatter)
  }
  const parts = formatter.formatToParts(at)
  const part = (type: string) => Number(parts.find((p) => p.type === type)?.value)
  const month = MONTHS[part("month") - 1]
  if (!month) return ""
  return `${part("day")} ${month} ${part("year")}`
}

/** "Thu 30 Oct · 17:00–18:00 Cairo time". */
export function sessionTimeLabel(
  booking: Pick<Booking, "startsAt" | "endsAt">,
  zone: string = SESSION_ZONE,
  zoneLabel: string = SESSION_ZONE_LABEL,
): string {
  return formatSlotRange(booking.startsAt, booking.endsAt, zone, zoneLabel)
}

export const MODE_LABEL: Record<TutoringMode, string> = {
  virtual: "Virtual",
  in_person: "In person",
  other: "Other",
}

// ── Controls: only from allowedActions ─────────────────────────────────────

export interface SessionActions {
  cancel: boolean
  complete: boolean
  review: boolean
  postNote: boolean
}

/**
 * Which controls S-37 / P-06 draws. `allowedActions` is the API's answer for
 * this viewer; a parent additionally needs to be the person who made the
 * request (P-06), and never reviews (a review is the student's, SC-12).
 */
export function sessionActions(
  booking: Pick<Booking, "allowedActions" | "requestedBy">,
  viewer: SessionViewer,
): SessionActions {
  const has = (action: Booking["allowedActions"][number]) => booking.allowedActions.includes(action)
  if (viewer === "parent") {
    const own = booking.requestedBy === "parent"
    return { cancel: own && has("cancel"), complete: own && has("complete"), review: false, postNote: false }
  }
  return { cancel: has("cancel"), complete: has("complete"), review: has("review"), postNote: has("post_note") }
}

// ── Fixed sentences (SPEC §d S-35, S-37) ───────────────────────────────────

export const CANCEL_RULE_LINE = "You can cancel up to 24 hours before the start."
export const COMPLETE_HINT =
  "Your tutor hasn't recorded this session. If it took place, you can mark it completed."
export const EXPIRED_LINE = "The tutor didn't reply before the start time."
export const ACCOUNT_TOO_NEW_LINE = "You can review once your account is 14 days old."
export const REVIEW_PRIVACY_LINE =
  "Your review text is checked by Lemely before others see it. Reviews show the season, not the date or your name."
export const COUNTING_NOTICE =
  "If you have sessions with this tutor, your grades in this subject are counted, without your name, in their results. You can opt out in Tutors & your data."
export const PLATFORM_CANCEL_LINE = "This session was cancelled by Lemely."
export const REASON_LABEL = "Their reason:"

const INSIDE_24H_SHORT = "It's less than 24 hours to the start, so you can't cancel this session."
const INSIDE_24H_MESSAGE = `${INSIDE_24H_SHORT} Message your tutor.`
const CANCEL_CUTOFF_MS = 24 * 3_600_000

/**
 * Row 18: inside 24 hours only the tutor can cancel. The sentence is shown when
 * the session is confirmed, has not started, the API offers no Cancel, and the
 * start is under 24 hours away. "Message your tutor" goes only to a student who
 * can still write a note; a parent is not told to message.
 */
export function insideCancelWindowNotice(
  booking: Pick<Booking, "allowedActions" | "requestedBy" | "effectiveState" | "startsAt">,
  viewer: SessionViewer,
  nowMs: number,
): string | null {
  if (booking.effectiveState !== "accepted") return null
  if (viewer === "parent" && booking.requestedBy !== "parent") return null
  const actions = sessionActions(booking, viewer)
  if (actions.cancel) return null
  const start = Date.parse(booking.startsAt)
  if (!(nowMs > start - CANCEL_CUTOFF_MS && nowMs < start)) return null
  return viewer === "student" && actions.postNote ? INSIDE_24H_MESSAGE : INSIDE_24H_SHORT
}

// ── What happened to a session that did not go ahead ───────────────────────

export interface StateNotice {
  /** The sentence. */
  lead: string
  /** Someone else's words, exactly as given; draw them as text after `REASON_LABEL`. */
  reason: string | null
}

function reasonOf(text: string | null): string | null {
  return text !== null && text.trim() !== "" ? text : null
}

/** A cancelled booking, in the voice that fits who cancelled it. */
export function cancelledNotice(
  booking: Pick<
    Booking,
    "effectiveState" | "cancelledBy" | "cancelledLate" | "cancelReason" | "tutor" | "student"
  >,
  viewer: SessionViewer,
): StateNotice | null {
  if (booking.effectiveState !== "cancelled") return null
  const tutor = booking.tutor.publicName
  switch (booking.cancelledBy) {
    case "system":
    case "platform_admin":
      // One sentence for every platform-side cause. The stored reason is not shown.
      return { lead: PLATFORM_CANCEL_LINE, reason: null }
    case "tutor":
      return {
        lead: booking.cancelledLate
          ? `${tutor} cancelled this session less than 24 hours before the start.`
          : `${tutor} cancelled this session.`,
        reason: reasonOf(booking.cancelReason),
      }
    case "student":
      return {
        lead: viewer === "student" ? "You cancelled this session." : `${booking.student.displayName} cancelled this session.`,
        reason: null,
      }
    case "parent":
      return { lead: "A parent cancelled this session.", reason: null }
    default:
      return { lead: "This session was cancelled.", reason: null }
  }
}

/** The one-sentence explanation for a session that is not confirmed or completed. */
export function stateNotice(
  booking: Pick<
    Booking,
    | "effectiveState"
    | "cancelledBy"
    | "cancelledLate"
    | "cancelReason"
    | "declineReason"
    | "tutor"
    | "student"
    | "allowedActions"
    | "requestedBy"
  >,
  viewer: SessionViewer,
): StateNotice | null {
  const tutor = booking.tutor.publicName
  switch (booking.effectiveState) {
    case "cancelled":
      return cancelledNotice(booking, viewer)
    case "declined":
      return { lead: `${tutor} declined this request.`, reason: reasonOf(booking.declineReason) }
    case "expired":
      return { lead: EXPIRED_LINE, reason: null }
    case "no_show":
      return {
        lead: `${viewer === "student" ? "Your tutor" : "The tutor"} marked this session as a no-show. If that's wrong, use Report and choose "The session outcome is wrong".`,
        reason: null,
      }
    case "requested":
      return {
        lead: `${viewer === "student" ? "Your request" : "This request"} is waiting for ${tutor} to reply.`,
        reason: null,
      }
    case "awaiting_outcome":
      // With the "Mark as completed" control the hint beside it says this already.
      if (sessionActions(booking, viewer).complete) return null
      return { lead: `This session has ended. ${tutor} hasn't recorded whether it took place yet.`, reason: null }
    default:
      return null
  }
}

// ── Reviews (S6, S7) ───────────────────────────────────────────────────────

export const REVIEW_TEXT_MAX = 1000

export type ReviewView =
  | { kind: "write" }
  | { kind: "opens"; line: string }
  | { kind: "tooNew"; line: string }
  | { kind: "existing"; stars: number; textState: MyReview["textState"]; canEdit: boolean }

/**
 * What the review area of S-37 shows. A review that exists is shown (and
 * editable until `editableUntil`); a new one only when the API lists `review`;
 * before that, when it opens; and once it has opened without a `review`, why.
 */
export function reviewView(
  booking: Pick<Booking, "allowedActions" | "requestedBy" | "effectiveState" | "review" | "reviewOpensAt">,
  viewer: SessionViewer,
  nowMs: number,
): ReviewView | null {
  if (viewer !== "student") return null
  if (booking.review !== null) {
    return {
      kind: "existing",
      stars: booking.review.stars,
      textState: booking.review.textState,
      canEdit: nowMs < Date.parse(booking.review.editableUntil),
    }
  }
  if (booking.effectiveState !== "completed") return null
  if (sessionActions(booking, viewer).review) return { kind: "write" }
  if (booking.reviewOpensAt === null) return null
  if (nowMs < Date.parse(booking.reviewOpensAt)) {
    return { kind: "opens", line: `You can review this session from ${formatTutorDate(booking.reviewOpensAt)}.` }
  }
  // The window is open and no Review is offered. The API withholds it from a
  // completed, unreviewed session for one reason only: the account is under
  // 14 days old (`core.booking.allowed_actions`, O10).
  return { kind: "tooNew", line: ACCOUNT_TOO_NEW_LINE }
}

export function reviewCreateBody(stars: number, text: string): ReviewCreate {
  const trimmed = text.trim()
  return { stars, text: trimmed === "" ? null : trimmed }
}

export interface ReviewEdit {
  initialStars: number
  stars: number
  text: string
  clearText: boolean
}

/**
 * The S7 body for an edit: only what changed, or null when nothing did (the API
 * refuses an empty update). The booking carries the stars but not the old text,
 * so the text box starts empty and means "replace"; `clearText` removes it, and
 * wins over anything typed.
 */
export function reviewUpdateBody({ initialStars, stars, text, clearText }: ReviewEdit): ReviewUpdate | null {
  const body: ReviewUpdate = {}
  if (stars !== initialStars) body.stars = stars
  if (clearText) body.clearText = true
  else if (text.trim() !== "") body.text = text.trim()
  return Object.keys(body).length === 0 ? null : body
}

/** Plain account of what happens to the student's review. Stars count at once; text waits for a check. */
export function reviewStatusLine(textState: MyReview["textState"]): string {
  switch (textState) {
    case "none":
      return "Your stars are counted. You didn't add any text."
    case "pending":
      return "Your stars are counted. Your text is waiting for Lemely's check."
    case "approved":
      return "Your review is published."
    case "rejected":
      return "Your stars are counted. Lemely didn't publish your text."
  }
}

// ── Where the session happens ──────────────────────────────────────────────

export type SessionPlace =
  | { kind: "link"; href: string; host: string }
  | { kind: "text"; label: string; text: string }

/**
 * The address to link for a meeting link, or null when it is not an http(s)
 * address. The server only stores links to allow-listed services; this keeps a
 * script, data or mail address from ever becoming a link even so.
 */
export function safeMeetingHref(link: string): string | null {
  try {
    const url = new URL(link)
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null
  } catch {
    return null
  }
}

const PLACE_STATES: readonly EffectiveState[] = ["accepted", "awaiting_outcome", "completed"]

/**
 * The meeting link, place or note for a session that is confirmed or was held;
 * null before the tutor accepts and once it is declined, cancelled or expired.
 */
export function sessionPlace(
  booking: Pick<Booking, "effectiveState" | "mode" | "meetingLink" | "locationDetail" | "otherModeNote">,
): SessionPlace | null {
  if (!PLACE_STATES.includes(booking.effectiveState)) return null
  if (booking.mode === "virtual" && booking.meetingLink) {
    const href = safeMeetingHref(booking.meetingLink)
    if (href === null) return { kind: "text", label: "Meeting link", text: booking.meetingLink }
    return { kind: "link", href, host: new URL(href).hostname }
  }
  if (booking.mode === "in_person" && booking.locationDetail) {
    return { kind: "text", label: "Meeting place", text: booking.locationDetail }
  }
  if (booking.mode === "other" && booking.otherModeNote) {
    return { kind: "text", label: "How you will meet", text: booking.otherModeNote }
  }
  return null
}

const COUNTED_STATES: readonly EffectiveState[] = ["requested", "accepted", "awaiting_outcome", "completed"]

/** Row 8b: the counting notice goes with a student's live or finished session, not a cancelled one. */
export function showCountingNotice(booking: Pick<Booking, "effectiveState">, viewer: SessionViewer): boolean {
  return viewer === "student" && COUNTED_STATES.includes(booking.effectiveState)
}

// ── Notes (C-21 and C-24) ──────────────────────────────────────────────────

/**
 * Whether a student's first note must wait for the safety notice (C-24): only
 * when the settings say it has not been read. Unknown (still loading) is not
 * "not read": the note is sent, and the server's 409 `safety_notice_required`
 * brings the notice up (O26).
 */
export function noteNeedsSafetyNotice(viewer: SessionViewer, acknowledged: boolean | null): boolean {
  return viewer === "student" && acknowledged === false
}

/** P-06's line under a read-only thread. */
export function parentNotesFootnote(childName: string): string {
  return `Notes are between ${childName} and the tutor. You can read them and report anything that worries you.`
}

// ── S-36 rows ──────────────────────────────────────────────────────────────

export interface SessionRowView {
  bookingId: string
  tutorName: string
  subjectName: string
  timeLabel: string
  modeLabel: string
  state: EffectiveState
  ariaLabel: string
}

export function sessionRowView(booking: Booking): SessionRowView {
  const timeLabel = sessionTimeLabel(booking)
  const tutorName = booking.tutor.publicName
  return {
    bookingId: booking.bookingId,
    tutorName,
    subjectName: booking.subject.name,
    timeLabel,
    modeLabel: MODE_LABEL[booking.mode],
    state: booking.effectiveState,
    ariaLabel: `${booking.subject.name} with ${tutorName}, ${timeLabel}, ${bookingStatusOf(booking.effectiveState).label}`,
  }
}

/**
 * Append `next` to `earlier`, dropping an item already present. A repeated item
 * keeps its place and takes the newer copy, so a refetched page never doubles a row.
 */
export function mergePages<T>(earlier: readonly T[], next: readonly T[], keyOf: (item: T) => string): T[] {
  const merged = new Map<string, T>()
  for (const item of earlier) merged.set(keyOf(item), item)
  for (const item of next) merged.set(keyOf(item), item)
  return [...merged.values()]
}

// ── Confirm sheets ─────────────────────────────────────────────────────────

export interface ConfirmCopy {
  title: string
  description: string
  consequence?: string
  confirmLabel: string
  pendingLabel: string
  cancelLabel: string
}

export function cancelSheetCopy(
  booking: Pick<Booking, "effectiveState" | "tutor" | "subject" | "startsAt" | "endsAt">,
): ConfirmCopy {
  const what = `${booking.subject.name} with ${booking.tutor.publicName}, ${sessionTimeLabel(booking)}.`
  if (booking.effectiveState === "requested") {
    return {
      title: "Withdraw this request?",
      description: what,
      consequence: "The tutor is told. To meet, you would send a new request.",
      confirmLabel: "Withdraw request",
      pendingLabel: "Withdrawing",
      cancelLabel: "Keep the request",
    }
  }
  return {
    title: "Cancel this session?",
    description: what,
    consequence: "The tutor is told. To meet again, you would send a new request.",
    confirmLabel: "Cancel session",
    pendingLabel: "Cancelling",
    cancelLabel: "Keep the session",
  }
}

export function completeSheetCopy(
  booking: Pick<Booking, "tutor" | "subject" | "startsAt" | "endsAt">,
): ConfirmCopy {
  return {
    title: "Mark this session as completed?",
    description: `${booking.subject.name} with ${booking.tutor.publicName}, ${sessionTimeLabel(booking)}. Only do this if the session took place.`,
    confirmLabel: "Mark as completed",
    pendingLabel: "Saving",
    cancelLabel: "Not yet",
  }
}

// ── Errors ─────────────────────────────────────────────────────────────────

export type SessionActionKind = "cancel" | "complete" | "review" | "note"

const FALLBACK: Record<SessionActionKind, string> = {
  cancel: "We couldn't cancel this session. Try again.",
  complete: "We couldn't mark this session completed. Try again.",
  review: "We couldn't save your review. Try again.",
  note: "We couldn't send your note. Try again.",
}

/**
 * The sentence for a failed session action: the SPEC's own wording where it has
 * one (inside 24 hours, account too new, contact details), the tutoring API's
 * sentence for any other code it sent on purpose, otherwise the action's
 * fallback. Never the raw `error.message`. Null when nothing failed.
 */
export function sessionActionError(error: unknown, action: SessionActionKind): string | null {
  if (error === null || error === undefined) return null
  const typed = tutoringErrorOf(error)
  if (typed === null) return FALLBACK[action]
  switch (typed.code) {
    case "cancel_window_closed":
      return INSIDE_24H_SHORT
    case "account_too_new":
      return ACCOUNT_TOO_NEW_LINE
    case "contact_details_not_allowed":
      return CONTACT_DETAILS_MESSAGE
    default:
      return typed.message
  }
}

// ── Paging hook shared by the S-36 list, the notes and the S-38 log ────────

interface PageOf<I> {
  items: I[]
  nextCursor: string | null
}

export interface PagedItems<I, P extends PageOf<I>> {
  /** Everything loaded so far, in order, without repeats. */
  items: readonly I[]
  /** The newest page's response, for fields that ride along (`canPost`). */
  page: P | undefined
  /** For `QueryState`: the first page's state, and "success" once something is on screen. */
  state: {
    status: "pending" | "error" | "success"
    data: readonly I[] | undefined
    error: unknown
    refetch: () => unknown
    fetchStatus: "fetching" | "paused" | "idle"
  }
  hasMore: boolean
  loadingMore: boolean
  moreFailed: boolean
  loadMore: () => void
  retryMore: () => void
}

/**
 * Cursor paging by "show more". One query is live at a time (the current
 * cursor's page); what came before is kept in state, so the "Show more" button
 * stays mounted and keeps focus while the next page loads. A refetch of the live
 * page (after a note is posted) replaces that page only.
 *
 * `usePage` is a named hook that takes the scope (a booking id, "upcoming") and
 * the cursor, so the rules of hooks hold at the call site. The caller keys the
 * component that uses this by its scope, which resets the paging.
 */
export function usePagedItems<S, I, P extends PageOf<I>>(
  usePage: (scope: S, cursor: string | null) => UseQueryResult<P, Error>,
  scope: S,
  keyOf: (item: I) => string,
): PagedItems<I, P> {
  const [cursor, setCursor] = useState<string | null>(null)
  const [earlier, setEarlier] = useState<readonly I[]>([])
  const [latest, setLatest] = useState<P | undefined>(undefined)
  const query = usePage(scope, cursor)
  // Keep the newest page that arrived, so a field like `canPost` does not
  // vanish for the moment the next page is loading.
  if (query.data !== undefined && query.data !== latest) setLatest(query.data)
  const items = useMemo(() => mergePages(earlier, query.data?.items ?? [], keyOf), [earlier, query.data, keyOf])
  const next = query.data?.nextCursor ?? null
  const onLaterPage = cursor !== null
  return {
    items,
    page: latest,
    state: onLaterPage
      ? { status: "success", data: items, error: null, refetch: query.refetch, fetchStatus: query.fetchStatus }
      : {
          status: query.status,
          data: query.data === undefined ? undefined : items,
          error: query.error,
          refetch: query.refetch,
          fetchStatus: query.fetchStatus,
        },
    hasMore: next !== null,
    loadingMore: onLaterPage && query.isPending,
    moreFailed: onLaterPage && query.isError,
    loadMore: () => {
      if (next === null) return
      setEarlier(items)
      setCursor(next)
    },
    retryMore: () => {
      void query.refetch()
    },
  }
}
