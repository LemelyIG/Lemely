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

/* Plan 04 sends display values: plan share in percentage points, credit part in credits. */
function span([lo, hi]: [number, number], unit: (n: number) => string, rangeUnit: string): string {
  return lo === hi ? unit(hi) : `${lo}–${hi}${rangeUnit}`
}
const pct = (n: number) => `${n}% of plan`

export function jobEstimateText(row: UsageJobRow): string {
  const parts = [
    row.estimatePercentOfPlan ? span(row.estimatePercentOfPlan, pct, "% of plan") : null,
    row.estimateCredits ? span(row.estimateCredits, (n) => formatCredits(n), " credits") : null,
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
  const parts = [
    row.percentOfPlan !== null ? pct(row.percentOfPlan) : null,
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
