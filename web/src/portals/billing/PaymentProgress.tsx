/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* Same copy and the same polling record as the checkout return page, so the dialog and the page never disagree. Failure tells the reader the charge is still processed and offers "Check again" through the compact C-11 ErrorState. */
import { useEffect, useRef } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { ErrorState } from "@/components/ui/state-views"
import { paymentPhase } from "@/lib/billingFormat"
import { invalidateOnPaid, returnCopy } from "@/lib/checkoutReturn"
import { invalidateBilling, usePaymentStatus } from "@/lib/hooks/useBillingApi"

/*
 * Inline readout for a merchant-initiated charge (upgrade proration, extra seats; spec §5.3,
 * §5.4). The charge settles by webhook, so the dialog polls the same payment record the
 * checkout return page polls, with the same copy. The meter, balance and plan behind the dialog
 * are stale the moment it lands, so billing is refreshed once per paid payment, as the return
 * page does.
 */

export function PaymentProgress({ paymentId }: { paymentId: string }) {
  const payment = usePaymentStatus(paymentId)
  const queryClient = useQueryClient()
  const settled = useRef<string | null>(null)
  const data = payment.data
  const phase = data ? paymentPhase(data.status) : null
  useEffect(() => {
    invalidateOnPaid(() => invalidateBilling(queryClient), settled, paymentId, phase)
  }, [paymentId, phase, queryClient])

  if (payment.isError) {
    return (
      <ErrorState
        compact
        heading="Couldn't check this payment"
        body="It is still processed on our side. Check again in a minute."
        action={{ label: "Check again", onClick: () => void payment.refetch() }}
      />
    )
  }
  const copy = data
    ? returnCopy(phase ?? "confirming", data.purpose, payment.pollingStopped)
    : returnCopy("confirming", "upgrade_proration", false)
  return (
    <div role="status" className="flex flex-col gap-1">
      <p className="m-0 text-body-md font-semibold text-on-surface">{copy.heading}</p>
      <p className="m-0 text-body-sm text-on-surface-variant">{copy.body}</p>
    </div>
  )
}
