import type { BillingInterval, EstimatePayer, EstimateResponse, PaymentStatus, SubscriptionStatus } from "@/lib/billingTypes"

/*
 * Pure formatting for every billing surface. `locale` defaults to `undefined` so the reader's
 * own conventions order the parts; tests pin a locale. Months are always named (see
 * `formatAdminDate` in portals/admin/data.ts for why a numeric month is unsafe here).
 */

export function formatMoney(amountMinor: number, currency: string, locale?: string): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    currencyDisplay: "code",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amountMinor / 100)
}

export function formatCredits(units: number, locale?: string): string {
  const n = new Intl.NumberFormat(locale).format(units)
  return `${n} ${units === 1 ? "credit" : "credits"}`
}

export function formatPercent(fraction: number): string {
  return `${Math.max(0, Math.round(fraction * 100))}%`
}

export function formatBillingDate(iso: string, locale?: string): string {
  return new Date(iso).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
}

export function intervalLabel(interval: BillingInterval): string {
  return interval === "month" ? "per month" : "per year"
}

export function isPercentPayer(payer: EstimatePayer): boolean {
  return payer === "seat" || payer === "allowance"
}

function range(low: number, high: number): string {
  return low === high ? `about ${high}` : `${low}–${high}`
}

/** "3–5 credits" or "2–4% of your monthly plan" (spec §2.4). */
export function estimateSentence(e: EstimateResponse): string {
  if (isPercentPayer(e.payer) && e.percentLow !== null && e.percentHigh !== null) {
    const amount = e.percentHigh < 1 ? "under 1%" : `${range(e.percentLow, e.percentHigh)}%`
    return e.payer === "seat" ? `${amount} of your seat's monthly allowance` : `${amount} of your monthly plan`
  }
  if (e.payer === "none") return "no charge"
  return e.low === e.high ? `about ${formatCredits(e.high)}` : `${e.low}–${e.high} credits`
}

/** One live subscription per beneficiary per audience (spec §4.3 partial unique index). */
export function isLiveSubscription(status: SubscriptionStatus | undefined): boolean {
  return status === "pending_first_payment" || status === "active" || status === "past_due"
}

export type PaymentPhase = "confirming" | "paid" | "failed" | "mismatch" | "reversed"

export function paymentPhase(status: PaymentStatus): PaymentPhase {
  switch (status) {
    case "created":
    case "pending":
      return "confirming"
    case "paid":
      return "paid"
    case "failed":
      return "failed"
    case "failed_mismatch":
      return "mismatch"
    case "refunded":
    case "partially_refunded":
    case "voided":
      return "reversed"
  }
}
