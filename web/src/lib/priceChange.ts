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

export function priceChangeNotice(
  args: { summary: BillingSummary; audience: Audience; /** A parent looking at a child's plan. */ forChild?: boolean },
  locale?: string,
): PriceChangeNotice | null {
  const { summary, audience } = args
  const owner = args.forChild ? "This plan" : "Your plan"
  const sub = summary.subscription
  if (!sub) return null
  const change = sub.pendingTermsChange
  // A payer who cancelled keeps the pending move on the server, but the plan ends first: the
  // plan card says so, and so must this. Only the platform's own cancel is explained here.
  const platformCancel = sub.cancelReason === "plan_terms_changed"
  const period = sub.currentPeriodEnd ? formatBillingDate(sub.currentPeriodEnd, locale) : null

  if (sub.cancelAtPeriodEnd) {
    if (!platformCancel || !period) return null
    return {
      variant: "ended",
      heading: `${owner} ends on ${period} because its price changed. Subscribe again to keep it.`,
      details: [],
      seats: null,
      canCancel: false,
    }
  }
  if (!change) return null

  const date = change.firstRenewalAt ? formatBillingDate(change.firstRenewalAt, locale) : period
  // What the renewal costs: the base price plus the extra seats the payer already holds.
  const extras = sub.pendingExtraSeats ?? sub.extraSeats
  const renewal = change.priceMinor + extras * change.extraSeatPriceMinor
  const price = `${formatMoney(renewal, sub.tier.currency, locale)} ${intervalLabel(sub.tier.interval)}`

  if (change.endsInsteadOfMoving) {
    return {
      variant: "ends",
      heading: `${owner} ends ${date ? `on ${date}` : "at your next renewal"}. Subscribe again to keep it at the new price.`,
      details: change.priceChanges ? [`New price: ${price}.`] : [],
      seats: null,
      canCancel: false,
    }
  }

  const details: string[] = []
  if (audience === "teacher" && extras > 0 && change.priceChanges) {
    details.push(`Includes ${extras} extra ${extras === 1 ? "seat" : "seats"} at ${formatMoney(change.extraSeatPriceMinor, sub.tier.currency, locale)} each.`)
  }
  if (change.allowanceChange === "more") details.push("You get a bigger usage allowance.")
  if (change.allowanceChange === "less") details.push("Your usage allowance gets smaller.")
  if (audience === "teacher") {
    if (change.includedSeatsChanges) details.push(`Included seats: ${change.includedSeats}.`)
    if (change.seatAllowanceChanges) details.push("Each seat's allowance changes.")
    if (extras === 0 && change.extraSeatPriceMinor !== (sub.tier.extraSeatPriceMinor ?? 0)) {
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
    heading: change.priceChanges ? `${owner} changes ${when}: ${price}.` : `${owner} changes ${when}.`,
    details,
    seats,
    canCancel: !sub.cancelAtPeriodEnd,
  }
}
