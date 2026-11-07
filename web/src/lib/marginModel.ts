import type { BarPoint } from "@/components/ui/bar-chart"
import type { MarginReport } from "@/lib/billingTypes"

/* Money and margin view models (spec §8.4; plan 07 `MarginReportDTO`). Revenue bars plot EGP
 * (major units), cost bars USD. A null EGP cost or margin means the server has no USD to EGP
 * rate: every helper here keeps that null a null, never a zero and never a margin. */

const DAY_MS = 24 * 60 * 60 * 1000
const RANGE_DAYS = 90
/** The server answers 422 for a window longer than this many days. */
export const MAX_RANGE_DAYS = 400
/** The server takes `egpPerUsd` > 0 and <= this. */
export const MAX_RATE = 10_000

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
 * is still visible. The server sends six-decimal strings. A nonzero cost too small to show
 * at four decimals reads "under USD 0.0001", never "USD 0.00". */
export function formatUsd(value: string | number): string {
  const n = typeof value === "number" ? value : Number(value)
  if (n > 0 && n < 0.00005) return "under USD 0.0001"
  return `USD ${new Intl.NumberFormat("en", { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(n)}`
}

/** The last 90 days as whole UTC days, both ends included: today and the 89 days before it. */
export function defaultRange(now: Date): DayRange {
  const to = now.toISOString().slice(0, 10)
  const from = new Date(now.getTime() - (RANGE_DAYS - 1) * DAY_MS).toISOString().slice(0, 10)
  return { from, to }
}

/** Milliseconds at 00:00 UTC of a `YYYY-MM-DD` day, or null for anything else, including a
 * day that does not exist (`2026-02-30`) and a five-digit year, which a date input allows. */
function dayMs(day: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null
  const ms = Date.parse(`${day}T00:00:00Z`)
  return Number.isNaN(ms) || new Date(ms).toISOString().slice(0, 10) !== day ? null : ms
}

export type RangeProblem = { field: "from" | "to"; message: string }

/** Why a typed range can't be sent, and which field to blame, or null when it can. */
export function rangeProblem(range: DayRange): RangeProblem | null {
  if (!range.from) return { field: "from", message: "Pick a start day." }
  if (!range.to) return { field: "to", message: "Pick an end day." }
  const from = dayMs(range.from)
  const to = dayMs(range.to)
  if (from === null) return { field: "from", message: "Use a full date, such as 2026-11-05." }
  if (to === null) return { field: "to", message: "Use a full date, such as 2026-11-05." }
  if (from > to) return { field: "to", message: "The end day is before the start day." }
  if ((to - from) / DAY_MS + 1 > MAX_RANGE_DAYS) return { field: "to", message: `A range can cover at most ${MAX_RANGE_DAYS} days.` }
  return null
}

/** The report window for a range of whole UTC days. The server's window is half-open
 * (`paid_at < end`), so the end is the start of the day after `to`: sending 23:59:59 would
 * drop the last second of the last day. */
export function windowOf(range: DayRange): { start: string; end: string } {
  const to = dayMs(range.to)
  if (to === null || dayMs(range.from) === null) throw new RangeError(`not a calendar day range: ${range.from} to ${range.to}`)
  return { start: `${range.from}T00:00:00Z`, end: `${new Date(to + DAY_MS).toISOString().slice(0, 10)}T00:00:00Z` }
}

/** Why a typed USD to EGP rate can't be sent, or null when it can (an empty box is fine: the
 * rate is optional and the report then has no EGP cost or margin). */
export function rateProblem(text: string): string | null {
  const t = text.trim()
  if (t === "") return null
  if (!/^\d+(\.\d+)?$/.test(t)) return "Enter a number, such as 50 or 48.5."
  const n = Number(t)
  if (n <= 0) return "The rate must be more than 0."
  if (n > MAX_RATE) return `The rate can be at most ${MAX_RATE.toLocaleString("en")}.`
  return null
}

/** The rate to send, or null for none. Only call with text `rateProblem` accepts. */
export function rateParam(text: string): string | null {
  const t = text.trim()
  return t === "" ? null : t
}

const RATE_KEY = "lemely.admin.margin.egpPerUsd"

/** The rate this browser last used, if it is still a valid one. The server stores no rate. */
export function loadRate(): string {
  try {
    const t = globalThis.localStorage?.getItem(RATE_KEY) ?? ""
    return rateProblem(t) === null ? t : ""
  } catch {
    return ""
  }
}

export function saveRate(text: string): void {
  try {
    if (rateParam(text) === null) globalThis.localStorage?.removeItem(RATE_KEY)
    else globalThis.localStorage?.setItem(RATE_KEY, text.trim())
  } catch {
    // Storage can be blocked; the rate then lasts for this visit only.
  }
}
