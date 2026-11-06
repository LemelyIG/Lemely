import type { PaymentPhase } from "@/lib/billingFormat"
import type { CheckoutResponse, PaymentPurpose } from "@/lib/billingTypes"

/*
 * Leaving for Paymob's hosted checkout and coming back (spec §5.1 steps 3–5). The redirect
 * back carries Paymob's own query parameters; none of them is read. State comes only from
 * `GET /billing/payments/{id}`. Where to send the payer afterwards is remembered here, per
 * payment, in sessionStorage (same tab), and only same-origin paths are honoured.
 */

const KEY = "lemely.billing.returnTo"

function isSamePath(path: string): boolean {
  return path.startsWith("/") && !path.startsWith("//")
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

export function defaultBillingPath(role: string | undefined): string {
  if (role === "student") return "/student/billing"
  if (role === "teacher" || role === "school_admin") return "/teacher/billing"
  if (role === "parent") return "/parent"
  return "/"
}

export function isSafeCheckoutUrl(url: string): boolean {
  return url.startsWith("https://") || isSamePath(url)
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
 * Whether the billing and usage caches should be refreshed now: once, when the payment is first
 * seen as paid. `alreadyDone` is the caller's once-per-payment guard.
 */
export function shouldInvalidateBilling(phase: PaymentPhase | null, alreadyDone: boolean): boolean {
  return phase === "paid" && !alreadyDone
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

export function returnCopy(phase: PaymentPhase, purpose: PaymentPurpose, pollingStopped: boolean): ReturnCopy {
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
      return PAID[purpose]
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
