/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useState } from "react"
import { Warning } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import {
  REFUND_FIELDS,
  canVoid,
  majorFromMinor,
  openRefunds,
  paymentActionState,
  refundAmountErrors,
  refundBody,
  refundOutcome,
  refundableMinor,
} from "@/lib/adminBillingModel"
import { paymentLabel } from "@/lib/adminOpsModel"
import type { AdminPaymentRow } from "@/lib/billingTypes"
import { useReconcilePayment, useRefundPayment, useVoidPayment } from "@/lib/hooks/useAdminBillingApi"
import { cn } from "@/lib/utils"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/*
 * Refund, void and "check with Paymob" for one payment (spec §6 refunds, §8.2). Shared by the
 * customer view and the payments list.
 *
 * A refund row is committed before Paymob is called, and a timeout leaves it `unknown`: Paymob
 * may have refunded. While any refund is open the server refuses a second one, so the only
 * control offered is the check that asks Paymob what happened. Copy never calls an unknown
 * outcome a failure; only a refusal from Paymob reads as one.
 */

/** What the last response said, for screen readers: success is silent, anything else is spoken. */
function spoken(payment: AdminPaymentRow | undefined): string {
  const last = payment?.refunds.at(-1)
  if (!payment || !last || last.status === "succeeded") return ""
  const o = refundOutcome(last, payment.currency)
  return `${o.label}. ${o.detail}`
}

/** Every refund and void attempt on a payment, newest last, each in plain words. */
export function RefundHistory({ payment }: { payment: AdminPaymentRow }) {
  if (payment.refunds.length === 0) return null
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {payment.refunds.map((r) => {
        const o = refundOutcome(r, payment.currency)
        return (
          <li key={r.id} className="flex items-start gap-2 text-body-sm">
            {o.tone === "attention" ? <Warning size={16} aria-hidden className="mt-0.5 shrink-0 text-on-surface-variant" /> : null}
            <span className="min-w-0">
              <span className={cn("block font-medium", o.tone === "error" ? "text-error" : "text-on-surface")}>{o.label}</span>
              <span className="block text-on-surface-variant">{o.detail}</span>
              <span className="block text-on-surface-variant">Reason: {r.reason}</span>
            </span>
          </li>
        )
      })}
    </ul>
  )
}

function CheckWithPaymob({ payment }: { payment: AdminPaymentRow }) {
  const reconcile = useReconcilePayment()
  const [open, setOpen] = useState(false)
  const count = openRefunds(payment).length
  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)} aria-label={`Check refund with Paymob for ${paymentLabel(payment)}`}>
        Check with Paymob
      </Button>
      <span role="status" className="sr-only">
        {spoken(reconcile.data)}
      </span>
      {open ? (
        <ReasonedFormDialog
          open
          onClose={() => setOpen(false)}
          title="Check with Paymob"
          fields={[]}
          initial={{}}
          submitLabel="Check with Paymob"
          mutation={reconcile}
          toBody={(_v, r) => ({ id: payment.id, body: { reason: r } })}
          reload="Reload this page"
          note={
            <p className="m-0 text-body-sm text-on-surface">
              {count === 1 ? "A refund on this payment has" : `${count} refunds on this payment have`} no confirmed outcome. This asks Paymob what
              happened and records the answer. It never sends a new refund.
            </p>
          }
        />
      ) : null}
    </>
  )
}

export function PaymentActions({ payment }: { payment: AdminPaymentRow }) {
  const refund = useRefundPayment()
  const voidPayment = useVoidPayment()
  const [open, setOpen] = useState<"refund" | "void" | null>(null)
  const state = paymentActionState(payment)
  const live = (
    <span role="status" className="sr-only">
      {spoken(refund.data ?? voidPayment.data)}
    </span>
  )
  if (state === "closed") return null
  if (state === "settling") {
    return (
      <>
        <CheckWithPaymob payment={payment} />
        {live}
      </>
    )
  }
  const remaining = refundableMinor(payment)
  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => setOpen("refund")} aria-label={`Refund ${paymentLabel(payment)}`}>
        Refund
      </Button>
      {canVoid(payment) ? (
        <Button size="sm" variant="ghost" onClick={() => setOpen("void")} aria-label={`Void ${paymentLabel(payment)}`}>
          Void
        </Button>
      ) : null}
      {live}
      {open === "refund" ? (
        <ReasonedFormDialog
          open
          onClose={() => setOpen(null)}
          title="Refund payment"
          fields={REFUND_FIELDS}
          initial={{ amountMajor: majorFromMinor(remaining) }}
          submitLabel="Refund"
          mutation={refund}
          toBody={(v, r) => ({ id: payment.id, body: refundBody(v, r) })}
          check={(v) => refundAmountErrors(v, remaining, payment.currency)}
          reload="Reload this page"
          note={
            <p className="m-0 text-body-sm text-on-surface">
              A full refund takes back this payment's credits that are not yet spent. A partial refund leaves them in place. If Paymob does not
              answer, the outcome is shown as unknown and a second refund is blocked until you check.
            </p>
          }
        />
      ) : null}
      {open === "void" ? (
        <ReasonedFormDialog
          open
          onClose={() => setOpen(null)}
          title="Void payment"
          fields={[]}
          initial={{}}
          submitLabel="Void"
          mutation={voidPayment}
          toBody={(_v, r) => ({ id: payment.id, body: { reason: r } })}
          reload="Reload this page"
          note={<p className="m-0 text-body-sm text-on-surface">Paymob voids only same-day transactions. Use refund otherwise. A void also takes back unspent credits.</p>}
        />
      ) : null}
    </>
  )
}
