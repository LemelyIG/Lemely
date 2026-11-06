import { ApiError } from "@/lib/api"
import type { Audience, BillingInterval, PublicTier } from "@/lib/billingTypes"

/* Public pricing links and preselection. The public catalogue has no ids, so a choice travels
 * by tier code through sign-in to the signed-in plans page, which matches it by code. */

/** The signed-in plans page with this tier preselected. */
export function planPath(tier: PublicTier): string {
  return `/${tier.audience}/billing/plans?plan=${encodeURIComponent(tier.code)}&interval=${tier.interval}`
}

export function chooseHref(tier: PublicTier): string {
  return `/login?next=${encodeURIComponent(planPath(tier))}`
}

export function packsHref(audience: Audience): string {
  return `/login?next=${encodeURIComponent(`/${audience}/billing/plans#packs`)}`
}

/** Sign-up that lands on the plans page afterwards (Task 18 carries `next` through verification). */
export function signupHref(audience: Audience, next: string = `/${audience}/billing/plans`): string {
  return `/signup/${audience}?next=${encodeURIComponent(next)}`
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
