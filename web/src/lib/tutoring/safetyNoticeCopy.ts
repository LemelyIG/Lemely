/*
 * The fixed safety copy of the tutoring marketplace (SPEC §d): the first-booking
 * notice (C-24), the fixed lines of the notes thread (C-21), the report reasons
 * and what blocking does.
 *
 * C-24 and the C-21 lines are FIXED by the SPEC and are copied from it word for
 * word. `safetyNotice.test.ts` parses them out of `docs/tutoring/SPEC.md`, so a
 * wording change has to be made in the SPEC first. They live here rather than in
 * the components so the node-only runner can compare them with the SPEC, and so
 * the screens that show them (S-35, S-37, P-06, T-18) share one string.
 *
 * Block copy states the effects `docs/tutoring/SPEC.md` §a.2 lists for a new
 * block, in one transaction: the live grant is revoked, the pair's future
 * sessions are cancelled (the 24-hour window does not apply), the student leaves
 * the tutor's independent classes, new requests and notes close, and notes stay
 * readable and reportable. Unblocking restores nothing (B3).
 */

import type { ReportCreate } from "@/lib/tutoringTypes"
import { tutoringErrorOf } from "./apiErrors"

// ── C-24 · the first-booking safety notice ─────────────────────────────────

export const SAFETY_NOTICE_TITLE = "Before your first session"

/** The last line of the notice, reused beside a safety-concern report. */
export const HELPLINE_LINE = "If someone is in danger, call 16000 (Child Helpline, Egypt)."

export const SAFETY_NOTICE_PARAGRAPHS: readonly string[] = [
  "Tutors on Lemely are adults you may not have met. Lemely looked at documents they uploaded. That is not a criminal-records check.",
  "Keep messages on Lemely. Don't share your phone number, WhatsApp or social media, and don't move the conversation somewhere else.",
  "For in-person sessions, meet somewhere public and tell a parent or another adult you trust where you will be.",
  "If anything makes you uncomfortable, stop, tell an adult you trust, and use Report. You can also block the tutor.",
  HELPLINE_LINE,
]

export const SAFETY_NOTICE_BUTTON = "I understand"

// ── C-21 · the notes thread ────────────────────────────────────────────────

export const NOTES_FIXED_LINE = "Notes can be reported. Lemely staff read notes only when one is reported."
export const NOTES_TUTOR_PARENTS_LINE = "This student's parents can read these notes."
export const NOTES_FROZEN_LINE = "Notes are paused while Lemely looks at a report."
export const NOTES_HIDDEN_PLACEHOLDER = "Removed by Lemely"

// ── Free text that carries a phone number, an email or a handle ───────────

/** Shown on a 422 `contact_details_not_allowed` wherever free text is entered (SPEC §d rules). */
export const CONTACT_DETAILS_MESSAGE =
  "To keep everyone safe, keep contact details off Lemely. Use the session notes instead."

// ── Reports ────────────────────────────────────────────────────────────────

export type ReportTargetType = ReportCreate["targetType"]
export type ReportReason = ReportCreate["reason"]

export interface ReportReasonOption {
  value: ReportReason
  label: string
}

/** The seven `reportreason` values, safety first, "something else" last. */
export const REPORT_REASONS: readonly ReportReasonOption[] = [
  { value: "safety_concern", label: "A safety concern" },
  { value: "inappropriate_content", label: "Inappropriate content" },
  { value: "harassment", label: "Harassment or pressure" },
  { value: "spam", label: "Spam or advertising" },
  { value: "fake_profile", label: "A fake or misleading profile" },
  { value: "disputed_outcome", label: "The session outcome is wrong" },
  { value: "other", label: "Something else" },
]

/**
 * The reasons offered for a target. A disputed outcome is about a session, and
 * an admin can only act on it by marking that booking completed (SPEC §a.3, A11),
 * so it is offered on a booking and nowhere else.
 */
export function reportReasonsFor(targetType: ReportTargetType): ReportReasonOption[] {
  return REPORT_REASONS.filter((reason) => reason.value !== "disputed_outcome" || targetType === "booking")
}

/** Longest `details` the database accepts (`ck_tutoring_reports_details_len`). */
export const REPORT_DETAILS_MAX = 1000

// ── Blocks ─────────────────────────────────────────────────────────────────

export interface BlockCopy {
  title: string
  intro: string
  effects: string[]
  confirmLabel: string
  cancelLabel: string
}

export function blockCopy(viewer: "student" | "tutor", name: string): BlockCopy {
  if (viewer === "student") {
    return {
      title: `Block ${name}?`,
      intro: "Blocking ends contact with this tutor.",
      effects: [
        "Your future sessions with this tutor are cancelled, even ones less than 24 hours away.",
        "They stop seeing your progress, and neither of you can send new requests or notes.",
        "If they teach an independent class you joined, you leave that class.",
        "Notes you already have stay readable, and you can still report them.",
        "You can unblock them later. That won't bring any of this back.",
      ],
      confirmLabel: "Block",
      cancelLabel: "Don't block",
    }
  }
  return {
    title: `Block ${name}?`,
    intro: "Blocking ends contact with this student.",
    effects: [
      "Your future sessions with this student are cancelled, even ones less than 24 hours away.",
      "You stop seeing their progress, and neither of you can send new requests or notes.",
      "If they joined one of your independent classes, they leave that class.",
      "Notes you already have stay readable, and either of you can still report them.",
      "You can unblock them later. That won't bring any of this back.",
    ],
    confirmLabel: "Block",
    cancelLabel: "Don't block",
  }
}

// ── Errors ─────────────────────────────────────────────────────────────────

/**
 * The sentence a safety sheet shows for a failed call: the tutoring API's own
 * wording for a code it sent on purpose (`report_exists`, `too_many_requests`),
 * otherwise `fallback`. Null when nothing failed. Never the raw `error.message`.
 */
export function safetyActionError(error: unknown, fallback: string): string | null {
  if (error === null || error === undefined) return null
  return tutoringErrorOf(error)?.message ?? fallback
}
