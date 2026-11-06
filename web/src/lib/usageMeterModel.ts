import { formatBillingDate, formatCredits } from "@/lib/billingFormat"
import type { AllowanceMeter, Audience, CreditBucket, SeatMeter } from "@/lib/billingTypes"

/*
 * View models for the usage meter, the credit balance and the debt notice. Pure, so every
 * band and sentence is unit-tested; the components only lay them out.
 *
 * "Used up" is deliberately not an error state: running through an allowance is the plan
 * working as designed (spec §2.1), and crimson means lost marks or genuine errors only
 * (DESIGN.md "The Red Means Lost Rule").
 */

export interface MeterModel {
  percent: number
  /** Clamped 0..100 for the bar. */
  barValue: number
  label: string
  note: string | null
  state: "ok" | "high" | "used_up"
}

function band(percent: number): MeterModel["state"] {
  if (percent >= 100) return "used_up"
  if (percent >= 80) return "high"
  return "ok"
}

export function allowanceMeterModel(meter: AllowanceMeter, locale?: string): MeterModel {
  const percent = Math.max(0, Math.round(meter.fraction * 100))
  const state = band(percent)
  return {
    percent,
    barValue: Math.min(100, percent),
    label: `Usage ${percent}%, resets ${formatBillingDate(meter.resetsAt, locale)}`,
    note:
      state === "used_up"
        ? "This month's plan is used up. Credits pay from here."
        : state === "high"
          ? "Most of this month's plan is used."
          : null,
    state,
  }
}

/** `SeatMeterDTO` carries no teacher name or subjects (M4). */
export function seatMeterModel(seat: SeatMeter, locale?: string): MeterModel {
  const percent = Math.max(0, Math.round((seat.fraction ?? 0) * 100))
  return {
    percent,
    barValue: Math.min(100, percent),
    label: `Seat from your teacher: ${percent}% used`,
    note: seat.resetsAt
      ? `Resets ${formatBillingDate(seat.resetsAt, locale)}.`
      : "This month's seat allowance starts with your first job.",
    state: band(percent),
  }
}

export interface CreditExpiryLine {
  key: string
  units: number
  label: string
  soon: boolean
}

const SOON_MS = 30 * 24 * 60 * 60 * 1000

export function creditExpiryLines(buckets: CreditBucket[], now: Date, locale?: string): CreditExpiryLine[] {
  const byDay = new Map<string, { units: number; at: string | null }>()
  for (const b of buckets) {
    if (b.remaining <= 0) continue
    const key = b.expiresAt === null ? "never" : b.expiresAt.slice(0, 10)
    const prev = byDay.get(key)
    byDay.set(key, { units: (prev?.units ?? 0) + b.remaining, at: b.expiresAt })
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => (a === "never" ? 1 : b === "never" ? -1 : a.localeCompare(b)))
    .map(([key, { units, at }]) => ({
      key,
      units,
      label:
        at === null
          ? `${formatCredits(units, locale)} never expire`
          : `${formatCredits(units, locale)} expire ${formatBillingDate(at, locale)}`,
      soon: at !== null && new Date(at).getTime() - now.getTime() <= SOON_MS,
    }))
}

export function debtSentence(debtUnits: number, audience: Audience): string | null {
  if (debtUnits <= 0) return null
  const amount = formatCredits(debtUnits)
  return audience === "student"
    ? `A recent job cost ${amount} more than your balance. New work that uses your own balance is paused until your next credit pack or plan renewal clears it.`
    : `A recent job cost ${amount} more than the balance. New jobs on this balance are paused until the next pack or renewal clears it.`
}
