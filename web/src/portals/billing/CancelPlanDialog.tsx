import { useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { formatBillingDate } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { Audience, SubscriptionView } from "@/lib/billingTypes"
import { useCancelSubscription } from "@/lib/hooks/useBillingApi"

/*
 * Cancel takes effect at period end; access continues until then (spec §2.6, §5.3). Unused
 * allowance ends with the period (no rollover), and a teacher's seats stop receiving monthly
 * allowances once the plan ends (spec §5.9). The route returns the subscription. A past-due plan
 * keeps working only until its grace date, so that is the date it is told, not the period end.
 * The result and any failure sit in persistent live regions, and focus moves to the result when
 * it replaces the confirm button.
 */

export function CancelPlanDialog({
  open,
  onClose,
  subscription,
  audience,
}: {
  open: boolean
  onClose: () => void
  subscription: SubscriptionView
  audience: Audience
}) {
  const cancel = useCancelSubscription()
  const statusRef = useRef<HTMLParagraphElement>(null)
  const cancelled = cancel.isSuccess
  useEffect(() => {
    if (cancelled) statusRef.current?.focus()
  }, [cancelled])

  const pastDue = subscription.status === "past_due" && subscription.graceUntil !== null
  const endIso = pastDue ? subscription.graceUntil : cancel.data?.currentPeriodEnd ?? subscription.currentPeriodEnd
  const end = endIso ? formatBillingDate(endIso) : "the end of this period"
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      dismissible={!cancel.isPending}
      title="Cancel your plan"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={cancel.isPending}>
            {cancelled ? "Close" : "Keep my plan"}
          </Button>
          {cancelled ? null : (
            <Button variant="primary" loading={cancel.isPending} onClick={() => cancel.mutate({ subscriptionId: subscription.subscriptionId })}>
              Cancel at period end
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-2 text-body-md text-on-surface">
        {cancelled ? null : (
          <>
            <p className="m-0">
              Your plan {pastDue ? "keeps working" : "stays active"} until {end}. After that, usage comes from credits only, and any
              unused allowance ends with the period.
            </p>
            {audience === "teacher" ? <p className="m-0">Seats stop getting monthly allowances when the plan ends.</p> : null}
          </>
        )}
        <p
          ref={statusRef}
          role="status"
          tabIndex={-1}
          className={cancelled ? "m-0 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary" : "sr-only"}
        >
          {cancelled ? `Cancelled. Your plan ends on ${end}.` : null}
        </p>
        <p role="alert" className={cancel.isError ? "m-0 text-body-sm text-error" : "sr-only"}>
          {cancel.isError ? billingFailureMessage(cancel.error, "cancel your plan") : null}
        </p>
      </div>
    </Modal>
  )
}
