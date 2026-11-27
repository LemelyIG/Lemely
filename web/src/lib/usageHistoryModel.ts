import { formatCredits } from "@/lib/billingFormat"
import type { MeteredAction, PaymentPurpose, Receipt, UsageJobRow } from "@/lib/billingTypes"

/* Row text for the usage history and receipts tables. Pure, unit-tested. */

const ACTIONS: Record<MeteredAction, string> = {
  mark_paper: "Paper marking",
  regrade: "Regrade",
  generate_quiz: "Quiz generation",
  preview_quiz: "Quiz preview",
  self_review: "Self-review",
  study_plan: "Weekly study plan",
  mark_quiz: "Quiz marking",
  generate_flashcards: "Flashcard generation",
}

export function actionLabel(action: MeteredAction): string {
  return ACTIONS[action]
}

/*
 * Plan 04 sends display values: plan share in percentage points (fractional, e.g. 1.37), credit
 * part in credits. The meter shows whole percents, so these do too: a positive share that would
 * round to 0 reads "<1%", never "0%", and a range whose low end rounds to 0 reads "up to N%".
 */
const whole = (n: number) => Math.round(n)

function pctText(n: number): string {
  return n > 0 && whole(n) === 0 ? "<1% of plan" : `${whole(n)}% of plan`
}

function pctRange([lo, hi]: [number, number]): string {
  const [l, h] = [whole(lo), whole(hi)]
  if (h === 0) return pctText(hi)
  if (l === h) return `${h}% of plan`
  return l === 0 ? `up to ${h}% of plan` : `${l}–${h}% of plan`
}

function creditRange([lo, hi]: [number, number]): string {
  return lo === hi ? formatCredits(hi) : `${lo}–${hi} credits`
}

export function jobEstimateText(row: UsageJobRow): string {
  const parts = [
    row.estimatePercentOfPlan ? pctRange(row.estimatePercentOfPlan) : null,
    row.estimateCredits ? creditRange(row.estimateCredits) : null,
  ].filter((x): x is string => x !== null)
  return parts.length > 0 ? parts.join(" + ") : "—"
}

export function jobStatusText(row: UsageJobRow): string {
  switch (row.status) {
    case "open":
      return "Running"
    case "settled":
      return "Done"
    case "released":
      return "Failed, not charged"
    case "expired":
      return "Timed out, not charged"
  }
}

export function jobChargeText(row: UsageJobRow): string {
  if (row.status === "open") return "Not charged yet"
  // A job that failed or timed out costs nothing, whatever numbers the row carries.
  if (row.status === "released" || row.status === "expired") return "No charge"
  const parts = [
    row.percentOfPlan !== null ? pctText(row.percentOfPlan) : null,
    row.credits !== null ? formatCredits(row.credits) : null,
  ].filter((x): x is string => x !== null)
  if (parts.length === 0) return "No charge"
  const base = parts.join(" + ")
  return row.debtCredits ? `${base} (${formatCredits(row.debtCredits)} went below zero)` : base
}

const PURPOSES: Record<PaymentPurpose, string> = {
  subscription_first: "Plan",
  subscription_renewal: "Plan renewal",
  upgrade_proration: "Plan upgrade",
  extra_seats: "Extra seats",
  credit_pack: "Credit pack",
  auto_topup: "Auto top-up",
}

export function purposeLabel(purpose: PaymentPurpose): string {
  return PURPOSES[purpose]
}

/** M9: `ReceiptDTO` has no refunded amount, so the status is named, not priced. */
export function receiptStatusText(receipt: Receipt): string | null {
  if (receipt.status === "refunded") return "Refunded"
  if (receipt.status === "partially_refunded") return "Partly refunded"
  return null
}

/**
 * What the history screen shows. Only the first page's failure is a full-page error: once any
 * page is loaded the list stays on screen, and a failed "Load more" is reported beside the
 * button (react-query v5 keeps `data` but flips `status` to "error" in that case).
 */
export function historyPhase(q: { data: { pages: { jobs: unknown[] }[] } | undefined }): "first-load" | "empty" | "list" {
  if (q.data === undefined) return "first-load"
  return q.data.pages.every((p) => p.jobs.length === 0) ? "empty" : "list"
}

export function moreLoadedText(added: number): string {
  return `${added} more ${added === 1 ? "job" : "jobs"} loaded`
}
