import { ApiError } from "@/lib/api"
import { formatBillingDate, formatCredits } from "@/lib/billingFormat"
import { billingErrorCode } from "@/lib/billingOutcome"
import type { AssistantRow, CapPeriod, CapUpdate, MeteredAction, SeatRow, SeatScopeUpdate, TeamView } from "@/lib/billingTypes"

/* Pure view models for the seats and assistants screens. */

/** Mirrors the backend seat-eligible set (`SEAT_ACTIONS`, index R12; Phase 04 added
 * `mark_quiz` and `generate_flashcards`). */
export const SEAT_ACTIONS = ["mark_paper", "self_review", "study_plan", "mark_quiz", "generate_flashcards"] as const satisfies readonly MeteredAction[]
export type SeatAction = (typeof SEAT_ACTIONS)[number]

export const SEAT_ACTION_COPY: Record<SeatAction, { label: string; hint: string | null }> = {
  mark_paper: { label: "Paper marking", hint: null },
  self_review: { label: "Self-review", hint: null },
  study_plan: {
    label: "Weekly study plans",
    hint: "Off by default. When on, the seat pays for the first plan per subject each week. Regenerating that week uses the student's own balance.",
  },
  mark_quiz: { label: "Quiz marking", hint: null },
  generate_flashcards: { label: "Flashcard generation", hint: null },
}

export function seatCapacityModel(team: TeamView) {
  const capacity = team.seatCapacity
  const used = team.seatsUsed
  return {
    used,
    capacity,
    free: Math.max(0, capacity - used),
    barValue: capacity > 0 ? Math.min(100, Math.round((used / capacity) * 100)) : 0,
    label: `${used} of ${capacity} seats used`,
    detail: `${team.includedSeats} included with your plan, ${team.extraSeats} extra`,
  }
}

export function seatStatusText(seat: SeatRow): string {
  if (seat.status === "leaving" && seat.leavesAt) return `Leaving on ${formatBillingDate(seat.leavesAt)}`
  return seat.status === "removed" ? "Removed" : "Active"
}

const period = (p: "month" | "total") => (p === "month" ? "a month" : "in total")
const num = (n: number) => new Intl.NumberFormat().format(n)

/** The parts of a seat's overflow line, so a screen can set the figures in the data face. */
export function seatCapParts(seat: SeatRow): { limit: string; used: string; period: string } | null {
  if (seat.capUnits === null) return null
  return { limit: num(seat.capUnits), used: num(seat.capUsedUnits), period: period(seat.capPeriod) }
}

export function seatCapText(seat: SeatRow): string {
  const p = seatCapParts(seat)
  return p ? `Up to ${p.limit} of your credits ${p.period} (${p.used} used)` : "No overflow"
}

export function assistantCapText(row: AssistantRow): string {
  if (row.capUnits === null) return "No limit"
  return `Up to ${formatCredits(row.capUnits)} ${period(row.capPeriod)} (${num(row.capUsedUnits)} used)`
}

export function scopeSummary(seat: SeatRow, subjects: { code: string; name: string }[]): string {
  const names = seat.scopeSubjects.map((code) => subjects.find((s) => s.code === code)?.name ?? code)
  const actions = seat.scopeActions
    .filter((a): a is SeatAction => (SEAT_ACTIONS as readonly string[]).includes(a))
    .map((a) => SEAT_ACTION_COPY[a].label)
  return `${names.join(", ") || "No subjects"} · ${actions.join(", ") || "No actions"}`
}

/* ── Seat editor: request bodies, validation and what changed ────────────── */

const isSeatAction = (a: string): a is SeatAction => (SEAT_ACTIONS as readonly string[]).includes(a)

/** Only the actions a seat can pay for, in catalogue order, once each. */
export function seatActionsIn(actions: readonly string[]): SeatAction[] {
  return SEAT_ACTIONS.filter((a) => actions.includes(a))
}

export function scopeBody(subjects: readonly string[], actions: readonly string[]): SeatScopeUpdate {
  return { subjects: [...new Set(subjects)], actions: seatActionsIn(actions.filter(isSeatAction)) }
}

const sameSet = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((x) => b.includes(x))

const sameScope = (a: SeatScopeUpdate, b: SeatScopeUpdate) => sameSet(a.subjects, b.subjects) && sameSet(a.actions, b.actions)

export function scopeChanged(seat: SeatRow, body: SeatScopeUpdate): boolean {
  return !sameScope(seatScope(seat), body)
}

/** The scope a seat holds now, restricted to what a seat can pay for. */
export function seatScope(seat: SeatRow): SeatScopeUpdate {
  return { subjects: seat.scopeSubjects, actions: seatActionsIn(seat.scopeActions) }
}

/** Largest overflow limit the editor accepts; the backend only requires zero or more. */
export const CAP_MAX_UNITS = 1_000_000

export type CapDraft = { ok: true; body: CapUpdate } | { ok: false; error: string }

/** The overflow part of the form as a request body, or the field error. Zero is a valid limit. */
export function capBody(overflow: boolean, raw: string, capPeriod: CapPeriod): CapDraft {
  if (!overflow) return { ok: true, body: { capUnits: null, capPeriod } }
  const text = raw.trim()
  if (text === "") return { ok: false, error: "Enter a credit limit." }
  if (!/^\d+$/.test(text)) return { ok: false, error: "Use a whole number, zero or more." }
  const units = Number(text)
  if (units > CAP_MAX_UNITS) return { ok: false, error: `Use ${num(CAP_MAX_UNITS)} or fewer.` }
  return { ok: true, body: { capUnits: units, capPeriod } }
}

export function capChanged(seat: SeatRow, body: CapUpdate): boolean {
  return body.capUnits !== seat.capUnits || (body.capUnits !== null && body.capPeriod !== seat.capPeriod)
}

export interface SeatDraft {
  subjects: readonly string[]
  actions: readonly string[]
  cap: CapUpdate
}

/**
 * What one press of "Save seat" must send: scope first, then the cap, each only when it differs
 * from what is already stored. `savedScope` is the scope this dialog has already saved (a failed
 * cap leaves the dialog open), which becomes the baseline: a retry does not resend it, and
 * reverting it afterwards does.
 */
export function planSeatSave(a: { seat: SeatRow; draft: SeatDraft; savedScope: SeatScopeUpdate | null }): {
  sendScope: SeatScopeUpdate | null
  sendCap: CapUpdate | null
} {
  const body = scopeBody(a.draft.subjects, a.draft.actions)
  const baseline = a.savedScope ?? seatScope(a.seat)
  return {
    sendScope: sameScope(baseline, body) ? null : body,
    sendCap: capChanged(a.seat, a.draft.cap) ? a.draft.cap : null,
  }
}

/** When the cap failed after the scope was saved, say so; `null` when nothing was saved first. */
export function partialSaveMessage(savedScope: SeatScopeUpdate | null, capError: unknown): string | null {
  if (savedScope === null || !capError) return null
  return `Your subjects and actions were saved, but the credit limit wasn't. ${teamFailureMessage(capError, "save the credit limit")}`
}

/* ── Seat counts (buy and remove extra seats) ───────────────────────────── */

export type SeatCountCheck = { ok: true; seats: number } | { ok: false; error: string }

/** A whole number from `min` to `max`. Never coerced: the teacher sees what is wrong. */
export function seatCountValidation(raw: string, max: number, min = 1): SeatCountCheck {
  const text = raw.trim()
  if (text === "") return { ok: false, error: "Enter how many seats." }
  if (!/^\d+$/.test(text)) return { ok: false, error: "Use a whole number." }
  const seats = Number(text)
  if (seats < min) return { ok: false, error: `Use at least ${min}.` }
  if (seats > max) return { ok: false, error: `Use ${max} or fewer.` }
  return { ok: true, seats }
}

/** Most extra seats that can be removed: no more than exist, and none a student holds. */
export function removableExtraSeats(team: Pick<TeamView, "extraSeats" | "seatCapacity" | "seatsUsed">): number {
  return Math.max(0, Math.min(team.extraSeats, team.seatCapacity - team.seatsUsed))
}

export const seatsWord = (n: number) => `${n} ${n === 1 ? "seat" : "seats"}`

/* ── Month end (the backend frees a removed seat at the first instant of the next UTC month) ── */

export function monthEndInstant(now: Date): string {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1)).toISOString()
}

/** "the end of November": the month the removal happens in, so it reads the same as the list's "Leaving on 1 Dec". */
export function monthEndLabel(now: Date, locale?: string): string {
  const month = now.toLocaleDateString(locale, { month: "long", timeZone: "UTC" })
  return `the end of ${month}`
}

/* ── Failure copy for seat writes (none of these charge anything) ───────── */

export function teamFailureMessage(err: unknown, action: string): string {
  const status = err instanceof ApiError ? err.status : -1
  if (status === 0) return "You're offline. Nothing was saved. Try again when you're back online."
  if (status === 403) return "Only the lead teacher can change seats."
  if (status === 404) return "That seat isn't there any more. Reload the page to see the current list."
  if (status === 429) return "Too many attempts. Wait a minute and try again."
  if (status === 422) {
    const code = billingErrorCode(err)
    if (code === "invalid_scope") return "Choose only the subjects and actions listed, then save again."
    if (code === "invalid_cap") return "The credit limit must be a whole number, zero or more."
    return `Couldn't ${action}. Check the details and try again.`
  }
  if (status === 409) return "That change isn't possible right now. Reload the page and try again."
  return `Couldn't ${action}. Try again.`
}

/** The team query's retry rule: a refusal or bad request will not change on a retry; a server or network failure gets one. */
export function teamRetry(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 1
}
