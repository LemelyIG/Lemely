import { paymentPhase } from "@/lib/billingFormat"
import { returnCopy } from "@/lib/checkoutReturn"
import { usePaymentStatus } from "@/lib/hooks/useBillingApi"

/*
 * Inline readout for a merchant-initiated charge (upgrade proration, extra seats; spec §5.3,
 * §5.4). The charge settles by webhook, so the dialog polls the same payment record the
 * checkout return page polls, with the same copy.
 */

export function PaymentProgress({ paymentId }: { paymentId: string }) {
  const payment = usePaymentStatus(paymentId)
  if (payment.isError) {
    return (
      <p role="alert" className="m-0 text-body-sm text-error">
        Couldn't check this payment. It is still processed on our side; reload this page in a minute.
      </p>
    )
  }
  const data = payment.data
  const copy = data
    ? returnCopy(paymentPhase(data.status), data.purpose, payment.pollingStopped)
    : returnCopy("confirming", "upgrade_proration", false)
  return (
    <div role="status" className="flex flex-col gap-1">
      <p className="m-0 text-body-md font-semibold text-on-surface">{copy.heading}</p>
      <p className="m-0 text-body-sm text-on-surface-variant">{copy.body}</p>
    </div>
  )
}
