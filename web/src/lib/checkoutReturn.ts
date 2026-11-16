import type { PaymentPhase } from "@/lib/billingFormat"
import type {
  Audience,
  BillingInterval,
  CheckoutResponse,
  PackCheckoutRequest,
  PaymentPurpose,
  PaymentStatusView,
  PlanTier,
  SubscriptionCheckoutRequest,
} from "@/lib/billingTypes"

/*
 * Leaving for Paymob's hosted checkout and coming back (spec §5.1 steps 3–5). The redirect
 * back carries Paymob's own query parameters; none of them is read. State comes only from
 * `GET /billing/payments/{id}`. Where to send the payer afterwards is remembered here, per
 * payment, in sessionStorage (same tab), and only same-origin paths are honoured.
 */

const KEY = "lemely.billing.returnTo"

/**
 * Any parse of a URL string runs against this fixed origin, so "same origin" means the same
 * thing in the browser and in the node test runner.
 */
const ORIGIN = "https://lemely.invalid"

/** Backslash, tab, CR, LF and every other control character: the URL parser rewrites or drops them. */
// eslint-disable-next-line no-control-regex
const UNSAFE_CHARS = /[\\\u0000-\u001f\u007f]/

/**
 * A path on this origin and nothing else. A leading "/" is not enough: "//host", "/\\host",
 * "/\t/host" and "/\n/host" all resolve to another host once the browser has normalised them,
 * so the string is parsed and its origin compared.
 */
function isSamePath(path: string): boolean {
  if (!path.startsWith("/") || path.startsWith("//") || UNSAFE_CHARS.test(path)) return false
  try {
    return new URL(path, ORIGIN).origin === ORIGIN
  } catch {
    return false
  }
}

function isHttpsUrl(url: string): boolean {
  if (!url.startsWith("https://") || UNSAFE_CHARS.test(url)) return false
  try {
    return new URL(url).protocol === "https:"
  } catch {
    return false
  }
}

/** `null` where there is no sessionStorage (the node test runner, a locked-down browser). */
function tabStorage(): Storage | null {
  return typeof sessionStorage === "undefined" ? null : sessionStorage
}

export function rememberReturnTo(paymentId: string, path: string, storage: Storage | null = tabStorage()): void {
  storage?.setItem(`${KEY}.${paymentId}`, path)
}

export function returnToFor(paymentId: string, fallback: string, storage: Storage | null = tabStorage()): string {
  const stored = storage?.getItem(`${KEY}.${paymentId}`) ?? null
  return stored !== null && isSamePath(stored) ? stored : fallback
}

/**
 * Where to send the payer when no path was remembered (a new tab from a bank app has no
 * sessionStorage): extra seats belong to the team page, everything else to billing.
 */
export function defaultReturnPath(purpose: PaymentPurpose | null | undefined, role: string | undefined): string {
  return purpose === "extra_seats" ? "/teacher/team" : defaultBillingPath(role)
}

export function defaultBillingPath(role: string | undefined): string {
  if (role === "student") return "/student/billing"
  if (role === "teacher" || role === "school_admin") return "/teacher/billing"
  if (role === "parent") return "/parent"
  return "/"
}

export function isSafeCheckoutUrl(url: string): boolean {
  return isHttpsUrl(url) || isSamePath(url)
}

/** Remember where to come back to, then leave for checkout. False when the URL is unsafe. */
export function startCheckoutRedirect(
  res: CheckoutResponse,
  returnTo: string,
  go: (url: string) => void = (url) => window.location.assign(url),
): boolean {
  if (!isSafeCheckoutUrl(res.checkoutUrl)) return false
  rememberReturnTo(res.paymentId, returnTo)
  go(res.checkoutUrl)
  return true
}

/**
 * Refresh the billing and usage caches once per paid payment. `settled` remembers the id of the
 * payment already refreshed for, so a re-render or a repeated "paid" poll does nothing, while a
 * different payment seen in the same mount still refreshes. Returns whether it refreshed.
 */
export function invalidateOnPaid(
  invalidate: () => void,
  settled: { current: string | null },
  paymentId: string,
  phase: PaymentPhase | null,
): boolean {
  if (phase !== "paid" || settled.current === paymentId) return false
  settled.current = paymentId
  invalidate()
  return true
}

/** The extra-seats field is a 0 to 200 number; anything else becomes the nearest valid value. */
export function clampExtraSeats(value: number): number {
  return Math.max(0, Math.min(200, Math.trunc(value) || 0))
}

/** The body of `POST /billing/subscriptions/checkout`. Only teacher plans carry extra seats. */
export function subscriptionCheckoutRequest(
  tier: Pick<PlanTier, "id">,
  audience: Audience,
  beneficiaryId: string | null,
  extraSeats: number,
): SubscriptionCheckoutRequest {
  return { planTierId: tier.id, beneficiaryId, extraSeats: audience === "teacher" ? clampExtraSeats(extraSeats) : 0 }
}

/** The body of `POST /billing/checkout/pack`. `beneficiaryId` is the linked child for a parent. */
export function packCheckoutRequest(pack: { id: string }, beneficiaryId: string | null): PackCheckoutRequest {
  return { creditPackId: pack.id, beneficiaryId }
}

/** The audience's tiers for one interval, cheapest first. */
export function tiersForInterval(tiers: PlanTier[], interval: BillingInterval): PlanTier[] {
  return tiers.filter((t) => t.interval === interval).sort((a, b) => a.priceMinor - b.priceMinor)
}

/** Open on the interval the payer already pays on; a held legacy plan or no plan opens on monthly. */
export function initialInterval(current: BillingInterval | null | undefined): BillingInterval {
  return current === "year" ? "year" : "month"
}

/** "1 student seat included", "20 student seats included". */
export function seatsIncludedLabel(seats: number): string {
  return `${seats} student ${seats === 1 ? "seat" : "seats"} included`
}

export interface ReturnCopy {
  heading: string
  body: string
}

const PAID: Record<PaymentPurpose, ReturnCopy> = {
  credit_pack: { heading: "Credits added", body: "Your credits are ready to use." },
  auto_topup: { heading: "Credits added", body: "Your credits are ready to use." },
  subscription_first: { heading: "Your plan is active", body: "This month's allowance is ready to use." },
  upgrade_proration: { heading: "Plan upgraded", body: "The extra allowance is ready now." },
  extra_seats: { heading: "Seats added", body: "The new seats are ready for students to join." },
  subscription_renewal: { heading: "Renewal paid", body: "Your plan continues for another period." },
}

/** The part of a payment status that decides what a paid upgrade or seat payment came to. */
export type PaymentResult = Pick<PaymentStatusView, "outcome" | "creditedUnits" | "voidReason">

/** How a paid payment ended: as bought, turned into credits, or received and being handled. */
export type PaidResult = "applied" | "credited" | "needs_attention"

/**
 * `outcome` decides. `credited` also covers a renewal seat row, whose `outcome` is null but whose
 * `creditedUnits` is set. Without either field the payment is simply as bought.
 */
export function paidResult(p: PaymentResult | undefined): PaidResult {
  if (p?.outcome === "needs_attention") return "needs_attention"
  if (p?.outcome === "credited" || (p?.outcome !== "applied" && typeof p?.creditedUnits === "number")) return "credited"
  return "applied"
}

/** Why the payment became credits, in as few words as will do (generic when unknown). */
const CREDITED_BODY: Record<string, string> = {
  plan_ended: "Your plan ended first, so we added this to your credits.",
  period_rolled: "Your plan renewed first, so we added this to your credits.",
  period_ended: "Your plan renewed first, so we added this to your credits.",
  superseded: "Another change went through first, so we added this to your credits.",
  not_an_upgrade_now: "Another change went through first, so we added this to your credits.",
  seats_changing: "Your seats changed first, so we added this to your credits.",
  seats_dropped: "Your seats changed first, so we added this to your credits.",
  seats_over_limit: "You're at the seat limit, so we added this to your credits.",
  seats_not_sold: "Your plan has no extra seats, so we added this to your credits.",
}

export const CREDITED_FALLBACK = "Your plan changed first, so we added this to your credits."

const NEEDS_ATTENTION: ReturnCopy = {
  heading: "Payment received, we're handling it",
  body: "We couldn't apply it. We'll fix it or refund you.",
}

/** The paid copy for a payment, by what it came to. */
function paidCopy(purpose: PaymentPurpose, payment: PaymentResult | undefined): ReturnCopy {
  const result = paidResult(payment)
  if (result === "needs_attention") return NEEDS_ATTENTION
  if (result === "credited") {
    return { heading: "Added to your credits", body: (payment?.voidReason && CREDITED_BODY[payment.voidReason]) || CREDITED_FALLBACK }
  }
  return PAID[purpose]
}

/**
 * Where "Try again" goes: back to where the payer started. A plan or pack is bought from the
 * plans page under the billing page; extra seats are bought from the team page itself, so that
 * remembered path is the target as it is.
 */
export function retryPath(purpose: PaymentPurpose, backTo: string): string {
  if (purpose === "extra_seats") return backTo
  return backTo === "/" || backTo === "/parent" ? backTo : `${backTo}/plans`
}

/** The label of the way back, which is the team page for extra seats and billing otherwise. */
export function backLabel(purpose: PaymentPurpose, confirming = false): string {
  const verb = confirming ? "Go to" : "Back to"
  return purpose === "extra_seats" ? `${verb} your team` : `${verb} billing`
}

export function returnCopy(
  phase: PaymentPhase,
  purpose: PaymentPurpose,
  pollingStopped: boolean,
  payment?: PaymentResult,
): ReturnCopy {
  switch (phase) {
    case "confirming":
      return pollingStopped
        ? {
            heading: "Still confirming",
            body: "Your bank hasn't confirmed this payment yet. You can leave this page: it is added to your account as soon as it's confirmed.",
          }
        : {
            heading: "Confirming your payment",
            body: "Paymob is confirming the payment with your bank. This usually takes a few seconds. Keep this page open.",
          }
    case "paid":
      return paidCopy(purpose, payment)
    case "failed":
      return {
        heading: "Payment didn't go through",
        body: "The payment wasn't completed, so nothing was added to your account. You can try again with the same card or a different one.",
      }
    case "mismatch":
      return {
        heading: "We couldn't confirm this payment",
        body: "The amount reported for this payment didn't match the order, so nothing was added. Our team has been alerted and will refund it. You don't need to pay again.",
      }
    case "reversed":
      return {
        heading: "This payment was reversed",
        body: "It was refunded or cancelled, so it doesn't add anything to your account.",
      }
  }
}
