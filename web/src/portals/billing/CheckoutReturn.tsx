/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
/* Glyph, heading, one line of body, the amount, then at most two actions. mismatch and reversed share the neutral tone with confirming; deliberate (PRODUCT.md: no red for money states the user did not cause) but the glyph alone has to carry the difference. */
import { useEffect, useRef, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { ArrowCounterClockwise, CheckCircle, Coins, Hourglass, Lifebuoy, WarningCircle, type Icon } from "@phosphor-icons/react"
import { Link, Navigate, useParams } from "react-router-dom"
import { BrandLockup } from "@/components/ui/brand-lockup"
import { Button, buttonVariants } from "@/components/ui/button"
import { MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { ErrorState } from "@/components/ui/state-views"
import { marketingLinks } from "@/portals/marketing/content"
import { useAuth } from "@/lib/auth/AuthContext"
import { formatMoney, paymentPhase, type PaymentPhase } from "@/lib/billingFormat"
import { backLabel, defaultBillingPath, defaultReturnPath, invalidateOnPaid, paidResult, retryPath, returnCopy, returnToFor } from "@/lib/checkoutReturn"
import { invalidateBilling, usePaymentStatus } from "@/lib/hooks/useBillingApi"
import { invalidateTeam } from "@/lib/hooks/useTeamApi"

/*
 * `/billing/return/:paymentId`: where Paymob's hosted checkout sends the payer back (spec §5.1
 * step 5). Paymob's query parameters are ignored; this page polls our own payment record.
 */

type Mark = PaymentPhase | "credited" | "attention"

const PHASE_MARK: Record<Mark, { Glyph: Icon; tone: string }> = {
  credited: { Glyph: Coins, tone: "text-primary" },
  attention: { Glyph: Lifebuoy, tone: "text-on-surface-variant" },
  confirming: { Glyph: Hourglass, tone: "text-on-surface-variant" },
  paid: { Glyph: CheckCircle, tone: "text-primary" },
  failed: { Glyph: WarningCircle, tone: "text-error" },
  mismatch: { Glyph: WarningCircle, tone: "text-on-surface-variant" },
  reversed: { Glyph: ArrowCounterClockwise, tone: "text-on-surface-variant" },
}

/** The state in a glyph, so it reads before the heading does. Decorative: the heading says it. */
function PhaseMark({ phase }: { phase: Mark }) {
  const { Glyph, tone } = PHASE_MARK[phase]
  return <Glyph aria-hidden="true" data-mark={phase} weight="duotone" className={`size-9 ${tone}`} />
}

/** `/billing` (plan 05's email links): the signed-in user's own billing page. */
export function BillingRedirect() {
  const { session } = useAuth()
  return <Navigate to={defaultBillingPath(session?.role)} replace />
}

export function CheckoutReturn() {
  const { paymentId = "" } = useParams<{ paymentId: string }>()
  const { session } = useAuth()
  const payment = usePaymentStatus(paymentId || null)
  // A bank app can return the payer in a new tab, where sessionStorage is empty: fall back by purpose.
  const backTo = returnToFor(paymentId, defaultReturnPath(payment.data?.purpose, session?.role))
  const queryClient = useQueryClient()
  const phaseNow = payment.data ? paymentPhase(payment.data.status) : null
  const purposeNow = payment.data?.purpose ?? null
  // The meter, credit balance and receipts on the screens behind this one are stale the moment
  // the payment lands, so refresh them once per paid payment.
  const settled = useRef<string | null>(null)
  useEffect(() => {
    invalidateOnPaid(
      () => {
        invalidateBilling(queryClient)
        // The seat count lives with the team, not in the billing caches.
        if (purposeNow === "extra_seats") invalidateTeam(queryClient)
      },
      settled,
      paymentId,
      phaseNow,
    )
  }, [paymentId, phaseNow, purposeNow, queryClient])

  let body: ReactNode
  if (payment.isError) {
    body = (
      <>
        <h1 id="return-heading" className="sr-only">Payment status</h1>
        <ErrorState
          heading="Couldn't load this payment"
          body="Check your connection and try again. If you paid, the payment is still confirmed on our side."
          action={{ label: "Try again", onClick: () => void payment.refetch() }}
        />
      </>
    )
  } else if (!payment.data) {
    body = (
      <div role="status" className="flex flex-col gap-3">
        <PhaseMark phase="confirming" />
        <h1 id="return-heading" className="m-0 text-display-sm text-on-surface">Confirming your payment</h1>
      </div>
    )
  } else {
    const data = payment.data
    const phase = paymentPhase(data.status)
    const copy = returnCopy(phase, data.purpose, payment.pollingStopped, data)
    const result = phase === "paid" ? paidResult(data) : null
    const mark: Mark = result === "credited" ? "credited" : result === "needs_attention" ? "attention" : phase
    const retryTo = retryPath(data.purpose, backTo)
    body = (
      <>
        <div role="status" className="flex flex-col gap-3">
          <PhaseMark phase={mark} />
          <h1 id="return-heading" className="m-0 text-display-sm text-on-surface">{copy.heading}</h1>
          <p className="m-0 text-body-md text-on-surface-variant">{copy.body}</p>
        </div>
        <p className="m-0 flex items-baseline justify-between gap-3 border-t border-outline-variant pt-4">
          <span className="text-body-sm text-on-surface-variant">
            {result === "credited" ? `Paid for: ${data.description}` : data.description}
          </span>
          <span className="text-data-md text-on-surface">{formatMoney(data.amountMinor, data.currency)}</span>
        </p>
        {result === "needs_attention" ? (
          <p className="m-0 text-body-sm text-on-surface-variant">
            Reference <span className="text-data-sm text-on-surface">{data.paymentId.slice(0, 8)}</span>
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {result === "needs_attention" ? (
            <a
              href={`${marketingLinks.contact}?subject=${encodeURIComponent(`Payment ${data.paymentId.slice(0, 8)}`)}`}
              className={buttonVariants({ variant: "primary" })}
            >
              Contact support
            </a>
          ) : null}
          {phase === "confirming" && payment.pollingStopped ? (
            <Button variant="primary" onClick={() => void payment.refetch()}>Check again</Button>
          ) : null}
          {phase === "failed" ? (
            <Link to={retryTo} className={buttonVariants({ variant: "primary" })}>Try again</Link>
          ) : null}
          {phase !== "confirming" || payment.pollingStopped ? (
            <Link to={backTo} className={buttonVariants({ variant: "secondary" })}>
              {backLabel(data.purpose, phase === "confirming")}
            </Link>
          ) : null}
        </div>
      </>
    )
  }

  return (
    <main
      id={MAIN_CONTENT_ID}
      tabIndex={-1}
      className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-surface px-page-mobile py-12 focus:outline-none"
    >
      <BrandLockup />
      <section aria-labelledby="return-heading" className="flex w-full max-w-[480px] flex-col gap-4 rounded-card border border-outline-variant bg-surface-container-lowest p-7">
        {body}
      </section>
    </main>
  )
}
