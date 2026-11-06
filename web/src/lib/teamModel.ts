import { formatBillingDate, formatCredits } from "@/lib/billingFormat"
import type { AssistantRow, MeteredAction, SeatRow, TeamView } from "@/lib/billingTypes"

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

export function seatCapText(seat: SeatRow): string {
  if (seat.capUnits === null) return "No overflow"
  return `Up to ${new Intl.NumberFormat().format(seat.capUnits)} of your credits ${period(seat.capPeriod)} (${seat.capUsedUnits} used)`
}

export function assistantCapText(row: AssistantRow): string {
  if (row.capUnits === null) return "No limit"
  return `Up to ${formatCredits(row.capUnits)} ${period(row.capPeriod)} (${row.capUsedUnits} used)`
}

export function scopeSummary(seat: SeatRow, subjects: { code: string; name: string }[]): string {
  const names = seat.scopeSubjects.map((code) => subjects.find((s) => s.code === code)?.name ?? code)
  const actions = seat.scopeActions
    .filter((a): a is SeatAction => (SEAT_ACTIONS as readonly string[]).includes(a))
    .map((a) => SEAT_ACTION_COPY[a].label)
  return `${names.join(", ") || "No subjects"} · ${actions.join(", ") || "No actions"}`
}
