import { ApiError } from "@/lib/api"
import { tutoringErrorOf } from "@/lib/tutoring/apiErrors"
import type { ListingState } from "@/lib/tutoring/profileSteps"
import type { AdminTutorState } from "@/lib/tutoring/queryKeys"
import type {
  AdminApprove,
  AdminBookingSummary,
  AdminNote,
  AdminTutorPage,
  ModerationItem,
  Note,
  ReplyModerate,
  ReportDetail,
  ReportItem,
  ReportResolution,
  ReportResolve,
  ReviewModerate,
} from "@/lib/tutoringTypes"

/*
 * T28 · what the platform-admin tutoring screens X-04..X-07 decide, apart from
 * how they look (SPEC §d, rows A1-A12). Every screen in
 * `portals/admin/screens/tutoring/` takes its rules and its sentences from here
 * so `tests/unit/adminTutoring.test.ts` can pin them without a renderer.
 *
 * The rules, and where each comes from:
 *
 *   - **Notes** are plain text of at most 2000 code points for a decision on a
 *     tutor (`tutor_approval_repo.MAX_NOTE_LENGTH`; the server answers 422
 *     `note_too_long`) and 1000 for the resolution of a report (the CHECK on
 *     `tutoring_reports.resolution_note`). Python counts code points, so an
 *     emoji is one, not two. Reject and suspend need a note: a rejection is read
 *     by the tutor (A4), and a suspension's notice tells the tutor to open their
 *     profile to see "the note from Lemely" (A5, W6 hand-off).
 *   - **Approve** is a claim that the admin looked at the documents. It stays
 *     shut until the "I looked at the documents" box is ticked AND every
 *     evidence file was opened from this page, so the box cannot be ticked
 *     first and believed later. A file with no download link cannot have been
 *     opened. `documentsSeen: true` is never built while the gate is shut.
 *   - **Resolutions** (A11) are limited to what the server can apply, so an admin
 *     is not offered a choice that only ends in 409 `resolution_not_applicable`.
 *     `booking_cancelled` needs a requested or accepted booking that has not
 *     started; `booking_completed` needs a disputed-outcome report on a booking
 *     awaiting its outcome or marked no-show.
 *     The server stays authoritative and its refusal is shown too.
 *   - **Party labels.** An admin sees a note's thread because someone reported
 *     it. The thread names a party ("Student", "Tutor"), never a person: the
 *     author's name is not read at all, so it cannot reach the page even if a
 *     payload carried one.
 */

// ── Limits ──────────────────────────────────────────────────────────────────

/** A note on a decision about a tutor (A3-A5, A12). */
export const DECISION_NOTE_MAX = 2000
/** A note on resolving a report (A11). */
export const RESOLUTION_NOTE_MAX = 1000
/** How long an evidence download link lives (SPEC §b.3, A2). */
export const EVIDENCE_LINK_TTL_SECONDS = 300

// ── Notes ───────────────────────────────────────────────────────────────────

export interface NoteRule {
  required: boolean
  max: number
}

/** Length as the server counts it: code points, so an emoji is one. */
export function noteLength(text: string): number {
  return Array.from(text).length
}

/** The note as it is sent: trimmed, or null when nothing is left. */
export function noteValue(raw: string): string | null {
  const trimmed = raw.trim()
  return trimmed === "" ? null : trimmed
}

/** Why `raw` cannot be sent under `rule`, or null when it can. Measured after trimming. */
export function noteError(raw: string, rule: NoteRule): string | null {
  const value = noteValue(raw)
  if (value === null) return rule.required ? "Write a note before you continue." : null
  const length = noteLength(value)
  if (length > rule.max) return `Shorten this to ${rule.max} characters or fewer. It is ${length} now.`
  return null
}

// ── Errors ──────────────────────────────────────────────────────────────────

/*
 * Codes the admin routes send that `TUTORING_ERROR_CODES` does not carry yet
 * (A3/A4 `note_required`, `documents_not_opened`; A4/A5/A12 `note_too_long`),
 * and one the shared list words for a booking. This table answers first; for
 * the codes the shared list holds with the same meaning it only ever fills gaps.
 */
const EXTRA_COPY: Readonly<Record<string, string>> = {
  // The shared sentence for this code talks about a booking; on A3-A5 and A12 it means
  // the tutor's listing state no longer allows the decision, usually because another admin acted.
  illegal_transition: "Someone has already decided this, or the profile has changed. Reload the page to see where it stands.",
  note_required: "Write a note before you continue.",
  // No number: A4, A5 and A12 allow 2000 characters and A11 allows 1000.
  note_too_long: "That note is too long. Shorten it and try again.",
  documents_not_opened: "Open every file before you approve. Reload the page to get new links.",
}

function codeOf(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  if (error.status < 400 || error.status > 499) return null
  const detail = error.detail
  if (detail === null || typeof detail !== "object" || Array.isArray(detail)) return null
  const code = (detail as { code?: unknown }).code
  return typeof code === "string" ? code : null
}

/**
 * One plain sentence for a failed admin action: the API's own sentence for a
 * refusal it sent on purpose, else `fallback`. A machine's words are never
 * repeated.
 */
export function adminFailureMessage(error: unknown, fallback: string): string {
  const code = codeOf(error)
  if (code !== null && code in EXTRA_COPY) return EXTRA_COPY[code]
  return tutoringErrorOf(error)?.message ?? fallback
}

// ── Dates ───────────────────────────────────────────────────────────────────

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" })

/** "30 Oct 2026". */
export function formatAdminDay(iso: string): string {
  return DAY.format(new Date(iso))
}

function clockParts(iso: string, timeZone: string | undefined) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZoneName: "short",
    timeZone,
  }).formatToParts(new Date(iso))
  const pick = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? ""
  return {
    day: `${pick("weekday")} ${pick("day")} ${pick("month")}`,
    time: `${pick("hour")}:${pick("minute")}`,
    zone: pick("timeZoneName"),
  }
}

/** "Fri 30 Oct · 17:00 GMT+2": the reader's own zone unless one is given, and the zone is always named. */
export function formatAdminInstant(iso: string, timeZone?: string): string {
  const { day, time, zone } = clockParts(iso, timeZone)
  return `${day} · ${time} ${zone}`
}

/** "Fri 30 Oct · 17:00–18:00 GMT+2". */
export function formatAdminRange(startsAt: string, endsAt: string, timeZone?: string): string {
  const start = clockParts(startsAt, timeZone)
  const end = clockParts(endsAt, timeZone)
  return `${start.day} · ${start.time}–${end.time} ${start.zone}`
}

/** "512 B", "2 KB", "1.5 MB". */
export function formatFileSize(bytes: number): string {
  const trim = (value: number) => String(Number(value.toFixed(1)))
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${trim(bytes / 1024)} KB`
  return `${trim(bytes / (1024 * 1024))} MB`
}

// ── X-04 · the queue ────────────────────────────────────────────────────────

export const MOCK_EMAIL_TITLE = "Email delivery: mock"

/** The banner X-04 shows when mail is not really being sent (SC-6); null for any other value. */
export function emailDeliveryNotice(
  delivery: AdminTutorPage["emailDelivery"] | undefined,
): { title: string; body: string } | null {
  if (delivery !== "mock") return null
  return {
    title: MOCK_EMAIL_TITLE,
    body: "Emails about tutors and sessions are recorded but not sent. People still see these notices in the app.",
  }
}

export const DEFAULT_QUEUE_STATE: AdminTutorState = "pending_review"

/** The listing states the queue can show, the one with work in it first. */
export const QUEUE_STATES: readonly { value: AdminTutorState; label: string }[] = [
  { value: "pending_review", label: "Waiting for review" },
  { value: "listed", label: "Listed" },
  { value: "suspended", label: "Suspended" },
  { value: "rejected", label: "Rejected" },
  { value: "closed", label: "Closed" },
]

const LISTING_LABEL: Record<ListingState, string> = {
  draft: "Draft",
  pending_review: "Waiting for review",
  listed: "Listed",
  rejected: "Rejected",
  suspended: "Suspended",
  closed: "Closed",
}

export function listingStateLabel(state: ListingState): string {
  return LISTING_LABEL[state]
}

/** What an empty queue says for `state`. */
export function queueEmpty(state: AdminTutorState): { heading: string; body: string } {
  if (state === "pending_review") {
    return {
      heading: "No applications waiting",
      body: "New and resubmitted profiles appear here, oldest first.",
    }
  }
  return {
    heading: `No ${LISTING_LABEL[state].toLowerCase()} tutors`,
    body: "Nothing is in this state right now.",
  }
}

// ── X-05 · decisions on a tutor ─────────────────────────────────────────────

export type TutorDecision = "approve" | "reject" | "suspend" | "close"

/** Close is final, so it sits last. */
export const CLOSE_CONFIRM = "Closing cancels future sessions, ends every student's sharing and can't be undone."

/**
 * `CLOSE_CONFIRM` is SPEC's sentence, word for word. A close also takes every
 * enrolment the tutor has in a class outside a school, including students who
 * never used tutoring, so the sheet says so in a second sentence.
 */
export const CLOSE_CONSEQUENCE = `${CLOSE_CONFIRM} It also removes students from the classes this tutor teaches outside a school.`

export const SUSPEND_CONSEQUENCE =
  "Suspending cancels the tutor's future sessions, ends every student's sharing and takes them out of the directory. Students and their parents are told. It also removes students who have booked or shared with this tutor from the classes this tutor teaches outside a school. Reinstating doesn't bring any of that back."

/** The decisions SPEC §a.3 allows from each listing state, in the order the page lays them out. */
export function availableDecisions(state: ListingState): TutorDecision[] {
  switch (state) {
    case "pending_review":
      return ["approve", "reject", "suspend", "close"]
    case "listed":
    case "rejected":
      return ["suspend", "close"]
    case "suspended":
      return ["approve", "close"]
    case "draft":
      return ["close"]
    case "closed":
      return []
  }
}

/** Approve on a suspended profile is a reinstatement (A3). */
export function decisionLabel(decision: TutorDecision, state: ListingState): string {
  if (decision === "approve") return state === "suspended" ? "Reinstate" : "Approve"
  if (decision === "reject") return "Reject"
  if (decision === "suspend") return "Suspend"
  return "Close"
}

export function decisionNoteRule(decision: TutorDecision): NoteRule {
  return { required: decision === "reject" || decision === "suspend", max: DECISION_NOTE_MAX }
}

export function decisionNoteError(decision: TutorDecision, raw: string): string | null {
  return noteError(raw, decisionNoteRule(decision))
}

/** The A4/A5/A12 body. */
export function decisionBody(_decision: TutorDecision, raw: string): AdminNote {
  return { note: noteValue(raw) }
}

export interface DecisionCopy {
  title: string
  consequence: string
  noteLabel: string
  noteHint: string
  confirmLabel: string
  doneLine: string
}

/** The confirm sheet of each decision that has one. Approve is inline on the page. */
export const DECISION_COPY: Readonly<Record<Exclude<TutorDecision, "approve">, DecisionCopy>> = {
  reject: {
    title: "Reject this application?",
    consequence: "The tutor reads your note, can fix the profile and can submit it again.",
    noteLabel: "Note for the tutor",
    noteHint: "Say what to fix. The tutor reads this.",
    confirmLabel: "Reject application",
    doneLine: "Application rejected.",
  },
  suspend: {
    title: "Suspend this tutor?",
    consequence: SUSPEND_CONSEQUENCE,
    noteLabel: "Note for the tutor",
    noteHint: "The tutor sees this note when they open their profile.",
    confirmLabel: "Suspend tutor",
    doneLine: "Tutor suspended.",
  },
  close: {
    title: "Close this tutor?",
    consequence: CLOSE_CONSEQUENCE,
    noteLabel: "Note (optional)",
    noteHint: "Kept in the approval history.",
    confirmLabel: "Close tutor",
    doneLine: "Tutor closed.",
  },
}

/** What to say after A3: reinstating can return a profile to review rather than the directory (SPEC §a.3). */
export function approveDoneLine(from: ListingState, result: ListingState): string {
  const verb = from === "suspended" ? "Reinstated" : "Approved"
  return result === "listed" ? `${verb}. The tutor is listed.` : `${verb}. The profile is back in review.`
}

// ── X-05 · the documents gate ───────────────────────────────────────────────

export interface EvidenceLink {
  evidenceId: string
  signedUrl: string | null
}

export interface ApproveInput {
  /** The "I looked at the documents" box. */
  documentsSeen: boolean
  evidence: readonly EvidenceLink[]
  /** Ids of the files opened from this page. */
  opened: ReadonlySet<string>
}

export interface ApproveGate {
  enabled: boolean
  /** Why Approve is shut, in a sentence; null when it is open. */
  reason: string | null
  /** Files not yet opened, counting any that have no link. */
  unopened: number
}

function filesPhrase(count: number): string {
  return count === 1 ? "1 file" : `${count} files`
}

/** Approve is open only when the box is ticked and every file was opened. A file with no link cannot have been. */
export function approveGate(input: ApproveInput): ApproveGate {
  const missingLink = input.evidence.filter((file) => file.signedUrl === null).length
  const unopened = input.evidence.filter(
    (file) => file.signedUrl === null || !input.opened.has(file.evidenceId),
  ).length
  if (missingLink > 0) {
    return {
      enabled: false,
      reason: `${filesPhrase(missingLink)} could not be opened. Reload the page to get new links.`,
      unopened,
    }
  }
  if (unopened > 0) {
    return { enabled: false, reason: `${filesPhrase(unopened)} not opened yet.`, unopened }
  }
  if (!input.documentsSeen) {
    return { enabled: false, reason: 'Tick "I looked at the documents" to continue.', unopened }
  }
  return { enabled: true, reason: null, unopened }
}

/** The A3 body, or null while the gate is shut: `documentsSeen: true` is never sent unearned. */
export function approveBody(input: ApproveInput, rawNote: string): AdminApprove | null {
  if (!approveGate(input).enabled) return null
  return { documentsSeen: true, note: noteValue(rawNote) }
}

/** Whole seconds left on links fetched at `loadedAtMs`; 0 once they are dead. */
export function evidenceLinkSecondsLeft(loadedAtMs: number, nowMs: number): number {
  const left = Math.ceil((loadedAtMs + EVIDENCE_LINK_TTL_SECONDS * 1000 - nowMs) / 1000)
  return Math.max(0, left)
}

export function evidenceLinksExpired(loadedAtMs: number, nowMs: number): boolean {
  return evidenceLinkSecondsLeft(loadedAtMs, nowMs) === 0
}

// ── X-06 · moderation ───────────────────────────────────────────────────────

export type ModerationDecision = "approved" | "rejected"

export type ModerationRequest =
  | { kind: "review"; id: string; body: ReviewModerate }
  | { kind: "reply"; id: string; body: ReplyModerate }

/**
 * The A7 or A8 call for a decision. A review carries the `revision` the queue
 * showed with its text, so a text edited since is refused rather than approved
 * unseen (RF-7); a reply cannot be edited and sends the decision alone.
 */
export function moderationRequest(item: ModerationItem, decision: ModerationDecision): ModerationRequest {
  if (item.kind === "review") {
    return { kind: "review", id: item.itemId, body: { decision, revision: item.revision } }
  }
  return { kind: "reply", id: item.itemId, body: { decision } }
}

export const MODERATION_FILTERS: readonly { value: "all" | "review" | "reply"; label: string }[] = [
  { value: "all", label: "Reviews and replies" },
  { value: "review", label: "Reviews" },
  { value: "reply", label: "Replies" },
]

export function moderationKindLabel(kind: ModerationItem["kind"]): string {
  return kind === "review" ? "Review text" : "Reply"
}

export function moderationDoneLine(kind: ModerationItem["kind"], decision: ModerationDecision): string {
  return `${moderationKindLabel(kind)} ${decision}.`
}

// ── X-06/X-07 · reports ─────────────────────────────────────────────────────

export type ReportReason = ReportItem["reason"]
export type ReportTarget = ReportItem["targetType"]
export type ReportState = ReportItem["state"]

const REASON_LABEL: Record<ReportReason, string> = {
  safety_concern: "Safety concern",
  inappropriate_content: "Inappropriate content",
  harassment: "Harassment",
  spam: "Spam",
  fake_profile: "Fake profile",
  disputed_outcome: "Disputed outcome",
  other: "Other",
}

const TARGET_LABEL: Record<ReportTarget, string> = {
  tutor_profile: "Tutor profile",
  review: "Review",
  review_reply: "Review reply",
  booking: "Booking",
  booking_note: "Session note",
}

const STATE_LABEL: Record<ReportState, string> = {
  open: "Open",
  dismissed: "Dismissed",
  actioned: "Actioned",
}

export function reportReasonLabel(reason: ReportReason): string {
  return REASON_LABEL[reason]
}

export function reportTargetLabel(target: ReportTarget): string {
  return TARGET_LABEL[target]
}

export function reportStateLabel(state: ReportState): string {
  return STATE_LABEL[state]
}

export const REPORT_STATES: readonly { value: ReportState; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "dismissed", label: "Dismissed" },
  { value: "actioned", label: "Actioned" },
]

export function isSafetyConcern(item: Pick<ReportItem, "reason">): boolean {
  return item.reason === "safety_concern"
}

const COMPLETED_BY_LABEL: Record<NonNullable<AdminBookingSummary["completedBy"]>, string> = {
  student: "The student",
  parent: "The parent",
  tutor: "The tutor",
  platform_admin: "Lemely",
}

/** Who marked a booking completed, in words. */
export function completedByLabel(value: NonNullable<AdminBookingSummary["completedBy"]>): string {
  return COMPLETED_BY_LABEL[value]
}

/** The 409 for a report someone else resolved first: the page should offer to reload it. */
export function isAlreadyResolved(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && codeOf(error) === "already_resolved"
}

/** The reporter by party, never by name. */
export function reporterLabel(party: ReportDetail["reporterParty"]): string {
  if (party === "student") return "A student"
  if (party === "parent") return "A parent"
  return "The tutor"
}

export const THREAD_VIEW_NOTICE =
  "Opening this report is logged, because it shows the session notes. Read only what the report needs."

const RESOLUTION_LABEL: Record<ReportResolution, string> = {
  dismissed: "Dismissed",
  content_hidden: "Content hidden",
  tutor_suspended: "Tutor suspended",
  booking_cancelled: "Booking cancelled",
  booking_completed: "Session marked completed",
}

export function resolutionLabel(resolution: ReportResolution): string {
  return RESOLUTION_LABEL[resolution]
}

export interface ResolutionOption {
  value: ReportResolution
  label: string
  help: string
}

const OPTION: Record<ReportResolution, ResolutionOption> = {
  dismissed: {
    value: "dismissed",
    label: "Dismiss",
    help: "Nothing needs to change. The report is closed.",
  },
  content_hidden: {
    value: "content_hidden",
    label: "Hide the content",
    help: "The reported text stops showing to students and tutors.",
  },
  tutor_suspended: {
    value: "tutor_suspended",
    label: "Suspend the tutor",
    help: "Cancels their future sessions and ends every student's sharing.",
  },
  booking_cancelled: {
    value: "booking_cancelled",
    label: "Cancel the booking",
    help: "Cancels this session before it starts.",
  },
  booking_completed: {
    value: "booking_completed",
    label: "Mark the session completed",
    help: "Records the session as held. For a disputed outcome.",
  },
}

type ResolutionContext = Pick<ReportDetail, "state" | "reason" | "targetType" | "bookingSummary">

/**
 * The tutor's listing state as A10 reports it. The shared `ReportDetail` type
 * does not carry the field yet, so it is read through this narrow shape.
 */
function tutorListingStateOf(context: ResolutionContext): string | null | undefined {
  return (context as { tutorListingState?: string | null }).tutorListingState
}

/** A suspension is applied from these states; an unknown state is offered, and the server decides. */
const SUSPENDABLE_FROM: ReadonlySet<string> = new Set(["pending_review", "listed", "rejected"])

function canSuspend(context: ResolutionContext): boolean {
  const state = tutorListingStateOf(context)
  return state === undefined || state === null || SUSPENDABLE_FROM.has(state)
}

const CONTENT_TARGETS: ReadonlySet<ReportTarget> = new Set(["review", "review_reply", "booking_note"])
const BOOKING_TARGETS: ReadonlySet<ReportTarget> = new Set(["booking", "booking_note"])

function hasStarted(context: ResolutionContext, now: Date): boolean {
  const summary = context.bookingSummary
  return summary !== null && now.getTime() >= new Date(summary.startsAt).getTime()
}

/**
 * The resolutions A11 can apply to this report now (SPEC §b.2 row A11, §a.3):
 * dismiss always; hide for review, reply and note targets; suspend for any
 * tutor who is pending review, listed or rejected (not one already suspended,
 * closed or a draft; A10's `tutorListingState`); cancel only a requested or accepted booking that has not started (for a
 * booking or a note's booking); mark completed only on a disputed-outcome
 * report about the booking itself, ended and awaiting its outcome or marked
 * no-show. Nothing once resolved. Mirrors `tutoring_reports_repo` (T25).
 */
export function resolutionOptions(context: ResolutionContext, now: Date): ResolutionOption[] {
  if (context.state !== "open") return []
  const options: ResolutionOption[] = [OPTION.dismissed]
  if (CONTENT_TARGETS.has(context.targetType)) options.push(OPTION.content_hidden)
  if (canSuspend(context)) options.push(OPTION.tutor_suspended)
  const summary = context.bookingSummary
  if (summary !== null && BOOKING_TARGETS.has(context.targetType)) {
    const active = summary.effectiveState === "requested" || summary.effectiveState === "accepted"
    if (active && !hasStarted(context, now)) options.push(OPTION.booking_cancelled)
    const awaiting = summary.effectiveState === "awaiting_outcome" || summary.effectiveState === "no_show"
    if (awaiting && context.targetType === "booking" && context.reason === "disputed_outcome") {
      options.push(OPTION.booking_completed)
    }
  }
  return options
}

/** Is `resolution` still among the choices at `now`? Checked again at submit, because the page was opened earlier. */
export function resolutionStillOffered(context: ResolutionContext, resolution: ReportResolution, now: Date): boolean {
  return resolutionOptions(context, now).some((option) => option.value === resolution)
}

/** Milliseconds until the booking starts while cancelling it is offered, else null: when the page must look again. */
export function cancelWindowMs(context: ResolutionContext, now: Date): number | null {
  if (!resolutionStillOffered(context, "booking_cancelled", now)) return null
  const summary = context.bookingSummary
  if (summary === null) return null
  return Math.max(0, new Date(summary.startsAt).getTime() - now.getTime())
}

/** Why the booking can no longer be cancelled, when that is the reason a choice is missing. */
export function resolutionUnavailable(context: ResolutionContext, now: Date): string | null {
  if (context.state !== "open") return null
  if (context.bookingSummary === null || !BOOKING_TARGETS.has(context.targetType)) return null
  return hasStarted(context, now)
    ? "Cancelling the booking is not offered because the session has already started."
    : null
}

export function resolutionNoteError(raw: string): string | null {
  return noteError(raw, { required: true, max: RESOLUTION_NOTE_MAX })
}

export interface ResolveReadiness {
  ready: boolean
  /** The reason Resolve is shut, when the reader cannot see it; null when ready or when the field itself explains. */
  hint: string | null
}

/** Resolve opens with a choice, a note within the limit and a connection. */
export function resolveReadiness(input: {
  choice: ResolutionOption | null
  note: string
  online: boolean
}): ResolveReadiness {
  if (!input.online) return { ready: false, hint: "You're offline. Reconnect to resolve." }
  if (input.choice === null) return { ready: false, hint: "Choose what should happen." }
  const problem = resolutionNoteError(input.note)
  if (problem === null) return { ready: true, hint: null }
  return { ready: false, hint: noteValue(input.note) === null ? "A note is needed before this can be recorded." : null }
}

/** The A11 body. */
export function resolveBody(resolution: ReportResolution, raw: string): ReportResolve {
  return { resolution, note: noteValue(raw) }
}

export interface ConfirmCopy {
  title: string
  body: string
  confirmLabel: string
}

/** What to say before a resolution that cannot be taken back; null for a dismissal. */
export function resolutionConfirm(resolution: ReportResolution): ConfirmCopy | null {
  switch (resolution) {
    case "dismissed":
      return null
    case "content_hidden":
      return {
        title: "Hide this content?",
        body: "The reported text stops showing to students and tutors. Staff can still read it here.",
        confirmLabel: "Hide content",
      }
    case "tutor_suspended":
      return { title: "Suspend this tutor?", body: SUSPEND_CONSEQUENCE, confirmLabel: "Suspend tutor" }
    case "booking_cancelled":
      return {
        title: "Cancel this booking?",
        body: "The session is cancelled before it starts. This can't be undone.",
        confirmLabel: "Cancel booking",
      }
    case "booking_completed":
      return {
        title: "Mark this session completed?",
        body: "The session is recorded as completed. This can't be undone.",
        confirmLabel: "Mark completed",
      }
  }
}

// ── X-07 · the thread and the snapshot ──────────────────────────────────────

/** A party, never a person. Reads nothing but the party. */
export function noteLabel(note: Pick<Note, "authorParty">): string {
  return note.authorParty === "student" ? "Student" : "Tutor"
}

export interface AdminNoteRow {
  noteId: string
  label: string
  body: string | null
  hidden: boolean
  createdAt: string
}

/** The thread as the admin reads it: in order, hidden bodies kept and marked, no author names. */
export function adminNoteRows(notes: readonly Note[]): AdminNoteRow[] {
  return notes.map((note) => ({
    noteId: note.noteId,
    label: noteLabel(note),
    body: note.body,
    hidden: note.hidden,
    createdAt: note.createdAt,
  }))
}

/**
 * The notes to show. A11 answers `notes: []` by design and the cache keeps its
 * answer, so after a resolution made here the notes of the last read stand. Any
 * other read of the report is the server's word.
 */
export function threadNotes(loaded: readonly Note[], current: readonly Note[], resolvedHere: boolean): readonly Note[] {
  return resolvedHere && current.length === 0 ? loaded : current
}

function humanise(key: string): string {
  const words = key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim()
    .toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** A `{ code, name }` reference such as an area or a subject: the name is the words. */
function namedOf(value: unknown): string | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null
  const name = (value as { name?: unknown }).name
  return typeof name === "string" && name !== "" ? name : null
}

function snapshotValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not set"
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  const named = namedOf(value)
  if (named !== null) return named
  if (Array.isArray(value)) {
    const parts = value.map((item) =>
      typeof item === "string" || typeof item === "number" ? String(item) : namedOf(item),
    )
    if (parts.every((part): part is string => part !== null)) return parts.join(", ")
  }
  return JSON.stringify(value)
}

/** A report's snapshot as labelled plain-text lines, in the order the server sent them. */
export function snapshotRows(snapshot: Record<string, unknown>): { label: string; value: string }[] {
  return Object.entries(snapshot).map(([key, value]) => ({ label: humanise(key), value: snapshotValue(value) }))
}
