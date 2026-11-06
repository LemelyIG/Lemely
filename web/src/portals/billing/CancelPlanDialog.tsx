import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { formatBillingDate } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { Audience, SubscriptionView } from "@/lib/billingTypes"
import { useCancelSubscription } from "@/lib/hooks/useBillingApi"

/*
 * Cancel takes effect at period end; access continues until then (spec §2.6, §5.3). Unused
 * allowance ends with the period (no rollover), and a teacher's seats stop receiving monthly
 * allowances once the plan ends (spec §5.9). The route returns the subscription.
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
  const end = subscription.currentPeriodEnd ? formatBillingDate(subscription.currentPeriodEnd) : "the end of this period"
  const endsOn = cancel.data?.currentPeriodEnd ? formatBillingDate(cancel.data.currentPeriodEnd) : end
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      dismissible={!cancel.isPending}
      title="Cancel your plan"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {cancel.isSuccess ? "Close" : "Keep my plan"}
          </Button>
          {cancel.isSuccess ? null : (
            <Button variant="primary" loading={cancel.isPending} onClick={() => cancel.mutate({ subscriptionId: subscription.subscriptionId })}>
              Cancel at period end
            </Button>
          )}
        </div>
      }
    >
      {cancel.isSuccess ? (
        <p role="status" className="m-0 text-body-md text-on-surface">
          Cancelled. Your plan ends on {endsOn}.
        </p>
      ) : (
        <div className="flex flex-col gap-2 text-body-md text-on-surface">
          <p className="m-0">
            Your plan stays active until {end}. After that, usage comes from credits only, and any unused allowance ends with the
            period.
          </p>
          {audience === "teacher" ? <p className="m-0">Seats stop getting monthly allowances when the plan ends.</p> : null}
          {cancel.isError ? (
            <p role="alert" className="m-0 text-body-sm text-error">
              {billingFailureMessage(cancel.error, "cancel your plan")}
            </p>
          ) : null}
        </div>
      )}
    </Modal>
  )
}
