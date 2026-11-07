import type { BarPoint } from "@/components/ui/bar-chart"
import type { MarginReport } from "@/lib/billingTypes"

/* Money and margin view models (spec §8.4; plan 07 `MarginReportDTO`). Revenue bars plot EGP
 * (major units), cost bars USD. A null EGP cost or margin means the server has no USD to EGP
 * rate: every helper here keeps that null a null, never a zero and never a margin. */

const DAY_MS = 24 * 60 * 60 * 1000
const RANGE_DAYS = 90

export type DayRange = { from: string; to: string }

/** Margin as a fraction of net revenue. Null without an EGP cost, or without positive net
 * revenue to divide by. */
export function marginShare(r: MarginReport): number | null {
  return r.marginMinor === null || r.revenue.netMinor <= 0 ? null : r.marginMinor / r.revenue.netMinor
}

/** Whole-number percent that keeps a negative margin negative (`formatPercent` clamps at 0). */
export function formatShare(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}

export function revenueBars(r: MarginReport): BarPoint[] {
  return [
    { label: "Recurring", value: r.revenue.recurringMinor / 100 },
    { label: "Packs", value: r.revenue.packsMinor / 100 },
    { label: "Refunded", value: r.revenue.refundedMinor / 100 },
  ]
}

export function costByActionBars(r: MarginReport): BarPoint[] {
  return r.cost.byAction.map((a) => ({ label: a.key ?? "Unattributed", value: Number(a.costUsd) }))
}

/** More than a fifth of jobs outside the estimated range means the estimator needs retuning. */
export function accuracyFlag(row: MarginReport["accuracy"][number]): "Retune" | null {
  return row.shareOutside > 0.2 ? "Retune" : null
}

/** USD with at least cents and at most four decimals, so a job costing a fraction of a cent
 * is still visible. The server sends six-decimal strings. */
export function formatUsd(value: string | number): string {
  const n = typeof value === "number" ? value : Number(value)
  return `USD ${new Intl.NumberFormat("en", { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(n)}`
}

/** The last 90 days as whole UTC days, both ends included. */
export function defaultRange(now: Date): DayRange {
  const to = now.toISOString().slice(0, 10)
  const from = new Date(now.getTime() - RANGE_DAYS * DAY_MS).toISOString().slice(0, 10)
  return { from, to }
}

export type RangeProblem = { field: "from" | "to"; message: string }

/** Why a typed range can't be sent, and which field to blame, or null when it can. Dates are
 * `YYYY-MM-DD`, which sort as text, so the order check needs no parsing. */
export function rangeProblem(range: DayRange): RangeProblem | null {
  if (!range.from) return { field: "from", message: "Pick a start day." }
  if (!range.to) return { field: "to", message: "Pick an end day." }
  if (range.from > range.to) return { field: "to", message: "The end day is before the start day." }
  return null
}
