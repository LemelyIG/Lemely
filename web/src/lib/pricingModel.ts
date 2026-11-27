import { ApiError } from "@/lib/api"
import { formatMoney, intervalLabel } from "@/lib/billingFormat"
import type { Audience, BillingInterval, PublicTier } from "@/lib/billingTypes"
import { safeNextPath, withNext } from "@/lib/nextPath"
import { describeQueryFailure } from "@/lib/queryFailure"

/* Public pricing links and preselection. The public catalogue has no ids, so a choice travels
 * by tier code through sign-in to the signed-in plans page, which matches it by code. */

/** The signed-in plans page with this tier preselected. */
export function planPath(tier: PublicTier): string {
  return `/${tier.audience}/billing/plans?plan=${encodeURIComponent(tier.code)}&interval=${tier.interval}`
}

/** `/login` or `/signup/…` carrying `next`, only when `next` is a safe same-origin path. */
function viaNext(base: string, next: string): string {
  return withNext(base, safeNextPath(next))
}

export function chooseHref(tier: PublicTier): string {
  return viaNext("/login", planPath(tier))
}

export function packsPath(audience: Audience): string {
  return `/${audience}/billing/plans#packs`
}

export function packsHref(audience: Audience): string {
  return viaNext("/login", packsPath(audience))
}

/** Sign-up that lands on the plans page afterwards (Task 18 carries `next` through verification). */
export function signupHref(audience: Audience, next: string = `/${audience}/billing/plans`): string {
  return viaNext(`/signup/${audience}`, next)
}

/**
 * Where "Choose plan" goes. A signed-in visitor skips sign-in (`/login` would drop `next` for an
 * existing session) and lands on the plans page with the tier preselected.
 */
export function chooseTarget(tier: PublicTier, signedIn: boolean): string {
  return signedIn ? planPath(tier) : chooseHref(tier)
}

export function packsTarget(audience: Audience, signedIn: boolean): string {
  return signedIn ? packsPath(audience) : packsHref(audience)
}

/** One interval's tiers, cheapest first; equal prices keep a stable name, then code, order. */
export function tiersForInterval(tiers: PublicTier[], interval: BillingInterval): PublicTier[] {
  return tiers
    .filter((t) => t.interval === interval)
    .sort((a, b) => a.priceMinor - b.priceMinor || a.name.localeCompare(b.name) || a.code.localeCompare(b.code))
}

/** "Extra seats EGP 30.00 each, billed per month". */
export function extraSeatsLine(priceMinor: number, currency: string, interval: BillingInterval): string {
  return `Extra seats ${formatMoney(priceMinor, currency)} each, billed ${intervalLabel(interval)}`
}

export function planPreselect(params: URLSearchParams): { code: string | null; interval: BillingInterval | null } {
  const interval = params.get("interval")
  return {
    code: params.get("plan") || null,
    interval: interval === "month" || interval === "year" ? interval : null,
  }
}

/** The seconds a 429 asks the visitor to wait, or null when the server gave no usable number. */
export function rateLimitSeconds(err: unknown): number | null {
  if (!(err instanceof ApiError) || err.status !== 429) return null
  return typeof err.retryAfter === "number" && Number.isFinite(err.retryAfter) && err.retryAfter > 0 ? Math.ceil(err.retryAfter) : null
}

/** The countdown sentence; at zero the wait is over and the sentence says so. */
export function rateLimitSentence(seconds: number): string {
  if (seconds <= 0) return "You can try again now."
  return `Too many requests. Try again in ${seconds} ${seconds === 1 ? "second" : "seconds"}.`
}

export function publicCatalogueFailure(err: unknown): string {
  if (err instanceof ApiError && err.status === 429) {
    const seconds = rateLimitSeconds(err)
    return seconds === null ? "Too many requests. Try again in a minute." : rateLimitSentence(seconds)
  }
  return "Couldn't load prices. Check your connection and try again."
}

/**
 * The body under the "Couldn't load prices" heading, so the heading is never repeated: a 429
 * without a usable wait says so, a dropped connection says what to check, and everything else
 * uses the app's shared failure sentence.
 */
export function publicCatalogueBody(err: unknown): string {
  if (err instanceof ApiError && err.status === 429) return "Too many requests. Try again in a minute."
  if (err instanceof ApiError && err.status === 0) return "Check your connection and try again."
  return describeQueryFailure(err)
}
