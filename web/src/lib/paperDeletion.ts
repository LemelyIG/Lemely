import type { DeletionRefusal } from "@/lib/studentTypes"

/*
 * Pure state for student paper deletion (design §2.1, §4 R7, §8), kept out
 * of the hook and the screen so it is testable without a renderer — the same
 * split `selfReview.ts` documents its own header with. `web/vitest.config.ts`
 * is Node-only (D3.20): nothing in this file may reach `document` or
 * `window`.
 */

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
]

/**
 * "21 October" — day-then-month, no year, no locale lookup. Built by hand
 * rather than through `toLocaleDateString`: that call reads the host's
 * locale, which this suite's Node environment does not pin, so the same
 * assertion ("21 October") would pass in en-GB and read "October 21" in
 * en-US. The result is a UI-facing date, not a machine one, so a fixed
 * English spelling matches every other hand-built date string in this
 * product (`Announcements.tsx`, `Profile.tsx`, ...).
 */
export function formatDay(iso: string): string {
  const date = new Date(iso)
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`
}

/**
 * Whole days remaining until `deadlineIso`, floored, never negative. A
 * restore window with 29.9 days left reads as "29 days", not "30" — rounding
 * up would promise a day the student does not actually have. A deadline
 * already passed reads as `0`, the same "gone" value a countdown at the
 * final second uses, rather than a negative number nothing on screen is
 * built to show.
 */
export function deleteCountdown(deadlineIso: string, nowIso: string): number {
  const deadline = new Date(deadlineIso).getTime()
  const now = new Date(nowIso).getTime()
  const msRemaining = deadline - now
  if (msRemaining <= 0) return 0
  return Math.floor(msRemaining / (24 * 60 * 60 * 1000))
}

/**
 * The sentence shown for a 409 hold (design §8: no pre-signalling, no
 * reason). `detail` is the server's own refusal sentence
 * (`"This paper can't be deleted yet."`) and this appends only the date the
 * hold lifts — never why. The forbidden-word check in the test file next to
 * this one exists because that "why" is exactly the leak QUALITY-BAR.md
 * rules out: the word "review" (or "flag"/"plagiar"/"integrity"/"score")
 * must never reach this sentence.
 */
export function deletionRefusal(refusal: DeletionRefusal): string {
  if (!refusal.deletableFrom) return refusal.detail
  return `${refusal.detail} You'll be able to delete it from ${formatDay(refusal.deletableFrom)}.`
}
