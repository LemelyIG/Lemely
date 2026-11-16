import { formatBillingDate, formatMoney, intervalLabel } from "@/lib/billingFormat"
import type { Audience, BillingSummary } from "@/lib/billingTypes"

/*
 * The payer's own notice of a plan-terms change (UD13-A): what changes, when, and what to do.
 * The email states no amount (UD13-E); this screen does. Allowance sizes are never stated
 * (spec §2.1): the server says only whether the allowance grows or shrinks.
 */

export interface PriceChangeNotice {
  /** `move`: new terms at a renewal. `ends`: the plan ends instead (Paymob cannot re-price it). */
  variant: "move" | "ends" | "ended"
  heading: string
  details: string[]
  /** Teachers holding more seats than the new plan has. `before` is a formatted date, or null. */
  seats: { remove: number; capacity: number; before: string | null } | null
  /** Cancelling at period end is still possible. */
  canCancel: boolean
}

export function priceChangeNotice(args: { summary: BillingSummary; audience: Audience }, locale?: string): PriceChangeNotice | null {
  const { summary, audience } = args
  const sub = summary.subscription
  if (!sub) return null
  const change = sub.pendingTermsChange
  const period = sub.currentPeriodEnd ? formatBillingDate(sub.currentPeriodEnd, locale) : null

  if (!change) {
    if (sub.cancelReason !== "plan_terms_changed" || !sub.cancelAtPeriodEnd || !period) return null
    return {
      variant: "ended",
      heading: `Your plan ends on ${period} because its price changed. Subscribe again to keep it.`,
      details: [],
      seats: null,
      canCancel: false,
    }
  }

  const date = change.firstRenewalAt ? formatBillingDate(change.firstRenewalAt, locale) : period
  const price = `${formatMoney(change.priceMinor, sub.tier.currency, locale)} ${intervalLabel(sub.tier.interval)}`

  if (change.endsInsteadOfMoving) {
    return {
      variant: "ends",
      heading: `Your plan ends ${date ? `on ${date}` : "at your next renewal"}. Subscribe again to keep it at the new price.`,
      details: change.priceChanges ? [`New price: ${price}.`] : [],
      seats: null,
      canCancel: false,
    }
  }

  const details: string[] = []
  if (change.allowanceChange === "more") details.push("You get a bigger usage allowance.")
  if (change.allowanceChange === "less") details.push("Your usage allowance gets smaller.")
  if (audience === "teacher") {
    if (change.includedSeatsChanges) details.push(`Included seats: ${change.includedSeats}.`)
    if (change.seatAllowanceChanges) details.push("Each seat's allowance changes.")
    if (change.extraSeatPriceMinor !== (sub.tier.extraSeatPriceMinor ?? 0)) {
      details.push(`Extra seats cost ${formatMoney(change.extraSeatPriceMinor, sub.tier.currency, locale)} each.`)
    }
  }

  let seats: PriceChangeNotice["seats"] = null
  if (audience === "teacher" && change.includedSeatsChanges && summary.seats) {
    const capacity = change.includedSeats + (sub.pendingExtraSeats ?? sub.extraSeats)
    const remove = summary.seats.used - capacity
    if (remove > 0) seats = { remove, capacity, before: date }
  }

  const when = date ? `on ${date}` : "at your next renewal"
  return {
    variant: "move",
    heading: change.priceChanges ? `Your plan changes ${when}: ${price}.` : `Your plan changes ${when}.`,
    details,
    seats,
    canCancel: !sub.cancelAtPeriodEnd,
  }
}
