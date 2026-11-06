import { useEffect, useRef, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { ArrowCounterClockwise, CheckCircle, Hourglass, WarningCircle, type Icon } from "@phosphor-icons/react"
import { Link, Navigate, useParams } from "react-router-dom"
import { BrandLockup } from "@/components/ui/brand-lockup"
import { Button, buttonVariants } from "@/components/ui/button"
import { MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { ErrorState } from "@/components/ui/state-views"
import { useAuth } from "@/lib/auth/AuthContext"
import { formatMoney, paymentPhase, type PaymentPhase } from "@/lib/billingFormat"
import { defaultBillingPath, invalidateOnPaid, returnCopy, returnToFor } from "@/lib/checkoutReturn"
import { invalidateBilling, usePaymentStatus } from "@/lib/hooks/useBillingApi"

/*
 * `/billing/return/:paymentId`: where Paymob's hosted checkout sends the payer back (spec §5.1
 * step 5). Paymob's query parameters are ignored; this page polls our own payment record.
 */

const PHASE_MARK: Record<PaymentPhase, { Glyph: Icon; tone: string }> = {
  confirming: { Glyph: Hourglass, tone: "text-on-surface-variant" },
  paid: { Glyph: CheckCircle, tone: "text-primary" },
  failed: { Glyph: WarningCircle, tone: "text-error" },
  mismatch: { Glyph: WarningCircle, tone: "text-on-surface-variant" },
  reversed: { Glyph: ArrowCounterClockwise, tone: "text-on-surface-variant" },
}

/** The state in a glyph, so it reads before the heading does. Decorative: the heading says it. */
function PhaseMark({ phase }: { phase: PaymentPhase }) {
  const { Glyph, tone } = PHASE_MARK[phase]
  return <Glyph aria-hidden="true" weight="duotone" className={`size-9 ${tone}`} />
}

/** `/billing` (plan 05's email links): the signed-in user's own billing page. */
export function BillingRedirect() {
  const { session } = useAuth()
  return <Navigate to={defaultBillingPath(session?.role)} replace />
}

export function CheckoutReturn() {
  const { paymentId = "" } = useParams<{ paymentId: string }>()
  const { session } = useAuth()
  const backTo = returnToFor(paymentId, defaultBillingPath(session?.role))
  const plansTo = backTo === "/" || backTo === "/parent" ? backTo : `${backTo}/plans`
  const payment = usePaymentStatus(paymentId || null)
  const queryClient = useQueryClient()
  const phaseNow = payment.data ? paymentPhase(payment.data.status) : null
  // The meter, credit balance and receipts on the screens behind this one are stale the moment
  // the payment lands, so refresh them once per paid payment.
  const settled = useRef<string | null>(null)
  useEffect(() => {
    invalidateOnPaid(() => invalidateBilling(queryClient), settled, paymentId, phaseNow)
  }, [paymentId, phaseNow, queryClient])

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
    const copy = returnCopy(phase, data.purpose, payment.pollingStopped)
    body = (
      <>
        <div role="status" className="flex flex-col gap-3">
          <PhaseMark phase={phase} />
          <h1 id="return-heading" className="m-0 text-display-sm text-on-surface">{copy.heading}</h1>
          <p className="m-0 text-body-md text-on-surface-variant">{copy.body}</p>
        </div>
        <p className="m-0 flex items-baseline justify-between gap-3 border-t border-outline-variant pt-4">
          <span className="text-body-sm text-on-surface-variant">{data.description}</span>
          <span className="text-data-md text-on-surface">{formatMoney(data.amountMinor, data.currency)}</span>
        </p>
        <div className="flex flex-wrap gap-2">
          {phase === "confirming" && payment.pollingStopped ? (
            <Button variant="primary" onClick={() => void payment.refetch()}>Check again</Button>
          ) : null}
          {phase === "failed" ? (
            <Link to={plansTo} className={buttonVariants({ variant: "primary" })}>Try again</Link>
          ) : null}
          {phase !== "confirming" || payment.pollingStopped ? (
            <Link to={backTo} className={buttonVariants({ variant: "secondary" })}>
              {phase === "confirming" ? "Go to billing" : "Back to billing"}
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
