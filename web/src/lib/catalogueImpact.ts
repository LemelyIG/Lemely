import { minorFromMajor, type FormValues } from "@/lib/adminBillingModel"
import type { AdminCreditPack, AdminPlanTier, PackPriceImpact } from "@/lib/billingTypes"

/*
 * What an edit does to customers who already pay (UD13-A, UD13-B), decided from the row the
 * dialog was opened on and the values typed so far. The row is frozen when the dialog opens, so
 * a refetch while the admin types never changes the warning or the version sent.
 *
 * A term change moves existing customers only at a renewal, after a notice; a pack price rise is
 * charged to auto top-ups from the next top-up. Both ask for a tick before saving.
 */

/** The server takes `priceMinor` for a pack up to ten billion piasters (`PositiveMoney`). */
const PACK_PRICE_MAX_MINOR = 10 ** 10

export interface TierImpactSettings {
  /** `billing_settings.price_change_notice_days`: how long a worse change waits. */
  noticeDays: number
  /** False on the fixed-amount fallback: Paymob cannot change a running renewal. */
  amountUpdatable: boolean
}

export interface TierImpact {
  customers: number
  noticeDays: number
  /** A price term changed and Paymob cannot re-price running renewals. */
  endsAtRenewal: boolean
}

const str = (v: FormValues, k: string) => String(v[k] ?? "").trim()

/** A whole number typed in a form, `null` while it is empty or half typed. */
function wholeNumber(v: FormValues, k: string): number | null {
  const t = str(v, k)
  return /^\d+$/.test(t) ? Number(t) : null
}

/** A seat field left empty is saved as 0, so it compares as 0. */
function seatNumber(v: FormValues, k: string): number | null {
  return str(v, k) === "" ? 0 : wholeNumber(v, k)
}

function seatMoney(v: FormValues, k: string): number | null {
  return str(v, k) === "" ? 0 : minorFromMajor(str(v, k))
}

/** True only when the typed value parses and differs; a half-typed value is not a change. */
const differs = (typed: number | null, stored: number) => typed !== null && typed !== stored

/** Which terms the typed values change. Name, features and on-sale are not terms. */
function termChanges(tier: AdminPlanTier, v: FormValues): { any: boolean; price: boolean } {
  const price = differs(minorFromMajor(str(v, "priceMajor")), tier.priceMinor)
  const allowance = differs(wholeNumber(v, "allowanceUnits"), tier.allowanceUnits)
  if (tier.audience !== "teacher") return { any: price || allowance, price }
  const seatPrice = differs(seatMoney(v, "extraSeatPriceMajor"), tier.extraSeatPriceMinor ?? 0)
  const included = differs(seatNumber(v, "includedSeats"), tier.includedSeats ?? 0)
  const seatAllowance = differs(seatNumber(v, "seatAllowanceUnits"), tier.seatAllowanceUnits ?? 0)
  return { any: price || allowance || seatPrice || included || seatAllowance, price: price || seatPrice }
}

/** The warning for a tier edit, or `null` when no customer is affected. */
export function tierImpact(tier: AdminPlanTier, v: FormValues, settings: TierImpactSettings): TierImpact | null {
  if (tier.liveSubscriptionCount <= 0) return null
  const changes = termChanges(tier, v)
  if (!changes.any) return null
  return { customers: tier.liveSubscriptionCount, noticeDays: settings.noticeDays, endsAtRenewal: changes.price && !settings.amountUpdatable }
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)
const count = (n: number) => new Intl.NumberFormat("en-US").format(n)

export function tierImpactLines(i: TierImpact): string[] {
  const lead =
    `${count(i.customers)} ${plural(i.customers, "customer is", "customers are")} on this plan. New customers get the new terms now. ` +
    `Current customers get an email and move at their first renewal after ${i.noticeDays} ${plural(i.noticeDays, "day", "days")}, ` +
    `if it's worse for them, or at their next renewal if it's better.`
  if (!i.endsAtRenewal) return [lead]
  return [lead, "Paymob can't change existing renewals, so their plans will end at that renewal and they'll be asked to subscribe again."]
}

/**
 * The price to preview when a pack edit raises the price for auto top-ups, else `null`. Only a
 * price the server would accept is asked about (the preview route refuses anything else).
 */
export function packPriceTarget(pack: AdminCreditPack, v: FormValues): number | null {
  if (pack.autoTopupCount <= 0) return null
  const next = minorFromMajor(str(v, "priceMajor"))
  if (next === null || next <= pack.priceMinor || next > PACK_PRICE_MAX_MINOR) return null
  return next
}

/** The warning for a pack price rise, or `null` when no auto top-up can charge. */
export function packImpactLines(impact: PackPriceImpact): string[] | null {
  const a = impact.autoTopupCount
  if (a <= 0) return null
  const lead = `${count(a)} ${plural(a, "customer tops", "customers top")} up automatically with this pack and will be charged the new price.`
  const m = impact.capBelowPriceCount
  if (m <= 0) return [lead]
  return [lead, `${count(m)} of them ${plural(m, "has", "have")} a monthly limit below it, so their auto top-up will stop until they raise the limit.`]
}

/** The tick is asked for only while a warning shows. */
export function confirmProblem(warned: boolean, v: FormValues): string | null {
  return warned && v.confirmImpact !== true ? "Tick the box to confirm." : null
}
