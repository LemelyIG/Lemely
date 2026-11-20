import type { BadgeTone } from "@/components/ui/badge"
import { humanize } from "@/lib/adminBillingModel"
import type { AdminPaymentRow, BillingHealth, PaymentStatus, ProblemQueue, SweeperJobHealth } from "@/lib/billingTypes"

/* Words and rules for the payments and health areas (spec §8.3, §8.5; plan 07 `ProblemQueueDTO`,
 * `BillingHealthDTO`). Pure, so the screens stay layout. */

export type ProblemKey = "mismatches" | "stalePending" | "missingCallbacks" | "hmacFailures" | "refundsNeedingAttention"

export interface ProblemSection {
  key: ProblemKey
  label: string
  /** One line on what the group is, so a row is never a bare status code. */
  hint: string
  /** Which kind of row the group holds. */
  rows: "payments" | "webhooks" | "refunds"
}

/** In the order plan 07 returns them and the order an admin should work them. */
export const PROBLEM_SECTIONS: readonly ProblemSection[] = [
  { key: "mismatches", label: "Amount mismatches", hint: "Paymob reported an amount that does not match the order.", rows: "payments" },
  { key: "stalePending", label: "Pending over an hour", hint: "Still waiting on Paymob after an hour. Reconcile asks Paymob what really happened.", rows: "payments" },
  { key: "missingCallbacks", label: "Missing callbacks", hint: "Marked paid, but Paymob never sent its callback.", rows: "payments" },
  { key: "hmacFailures", label: "HMAC failures", hint: "Callbacks that failed the signature check.", rows: "webhooks" },
  {
    key: "refundsNeedingAttention",
    label: "Refunds needing attention",
    hint: "Refunds and voids with no confirmed outcome. Open the payment under All payments and use Check with Paymob.",
    rows: "refunds",
  },
]

/**
 * A queued refund row carries an amount but no currency or payment id (plan 07 `RefundDTO`).
 * Paymob here settles in Egyptian pounds only, so the queue words its amount in that.
 */
export const QUEUE_REFUND_CURRENCY = "EGP"

/**
 * How many rows a group counts. The HMAC group counts the 24-hour figure when the server listed
 * fewer rows than it counted, so a capped list can never read as a smaller problem.
 */
export function sectionCount(q: ProblemQueue, key: ProblemKey): number {
  return key === "hmacFailures" ? Math.max(q.hmacFailures.length, q.hmacFailures24h) : q[key].length
}

export function problemCount(q: ProblemQueue): number {
  return PROBLEM_SECTIONS.reduce((sum, s) => sum + sectionCount(q, s.key), 0)
}

export const PAYMENT_STATUS_OPTIONS: { value: PaymentStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "created", label: "Created" },
  { value: "pending", label: "Pending" },
  { value: "paid", label: "Paid" },
  { value: "failed", label: "Failed" },
  { value: "failed_mismatch", label: "Amount mismatch" },
  { value: "refunded", label: "Refunded" },
  { value: "partially_refunded", label: "Partly refunded" },
  { value: "voided", label: "Voided" },
]

/**
 * Whether the Paymob transaction inquiry can still change this payment. Only an open payment
 * (`created` or `pending`) is asked: plan 07 `reconcile_payment_now` returns any other status
 * untouched, so offering Reconcile on a failed payment would write an audit row and never ask
 * Paymob. Paid, failed, refunded and mismatched payments are settled here.
 */
export function canReconcile(status: PaymentStatus): boolean {
  return status === "created" || status === "pending"
}

/** Only a payment that really failed, or whose amount did not match, is crimson. */
const PAYMENT_TONE: Record<PaymentStatus, BadgeTone> = {
  paid: "ok",
  created: "info",
  pending: "info",
  partially_refunded: "info",
  refunded: "sage",
  voided: "sage",
  failed: "err",
  failed_mismatch: "err",
}

export function paymentTone(status: PaymentStatus): BadgeTone {
  return PAYMENT_TONE[status]
}

/**
 * The reconcile answer, worded for what the server really knows. A 200 with an open status can
 * also mean the inquiry itself errored (the server leaves the payment as it was), so an open
 * payment is never described as checked; only a settled answer says Paymob was asked.
 */
export function reconcileNotice(p: Pick<AdminPaymentRow, "id" | "paymobOrderId" | "status">): string {
  const order = p.paymobOrderId ?? p.id
  if (p.status === "pending" || p.status === "created") return `Paymob has not reported a final result. Order ${order} is still pending.`
  if (p.status === "failed") return `Order ${order} is now marked failed.`
  return `Checked with Paymob. Order ${order} is ${humanize(p.status).toLowerCase()}.`
}

/** How a payment is named to a screen reader and in a dialog: its Paymob order, else a short id. */
export function paymentLabel(p: Pick<AdminPaymentRow, "id" | "paymobOrderId">): string {
  return p.paymobOrderId ? `order ${p.paymobOrderId}` : `payment ${p.id.slice(0, 8)}`
}

/**
 * True while the data on screen is older than the last attempt: React Query v5 keeps `data` but
 * flips `status` to "error" when a background refresh fails. A failed "Load more" is not one.
 */
export function refreshFailed(query: { status: "pending" | "error" | "success"; data: unknown; isFetchNextPageError?: boolean }): boolean {
  return query.data !== undefined && query.status === "error" && !query.isFetchNextPageError
}

/** Plan 07 `_QUEUE_LIMIT`: each problem group lists at most this many entries and sends no total. */
export const QUEUE_LIST_CAP = 100

export function webhookErrorText(h: BillingHealth): string {
  if (h.webhookErrorRate === null) return `No webhooks in ${h.windowHours} hours`
  const pct = Math.round(h.webhookErrorRate * 1000) / 10
  const failures = `${h.hmacFailures} HMAC failure${h.hmacFailures === 1 ? "" : "s"}`
  return `${pct}% failed (${failures}, ${h.verifiedEvents} verified) in ${h.windowHours} hours`
}

export function jobOutcomeText(job: SweeperJobHealth): string {
  if (job.neverRun) return "Never run"
  if (job.lastOutcome === "failed") return `Failed${job.lastError ? `: ${job.lastError}` : ""} (${job.consecutiveFailures} in a row)`
  return "OK"
}

/** What the job has done in total, from the counters the server keeps. */
export function jobRunsText(job: SweeperJobHealth): string {
  if (job.neverRun || job.totalRuns === 0) return "No runs recorded"
  const runs = `${job.totalRuns} run${job.totalRuns === 1 ? "" : "s"}`
  return job.totalFailures > 0 ? `${runs}, ${job.totalFailures} failed` : runs
}
