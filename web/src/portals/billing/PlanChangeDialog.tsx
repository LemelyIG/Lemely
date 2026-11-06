import { useEffect, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { PlanTier, SavedCardView, SubscriptionView } from "@/lib/billingTypes"
import { useDowngrade, useUpgrade, useUpgradeQuote } from "@/lib/hooks/useBillingApi"
import { PaymentProgress } from "./PaymentProgress"

/*
 * Upgrade now, downgrade at period end (spec §2.6, §5.3). An upgrade is quoted first
 * (`…/upgrade/quote`, no side effects) so the payer sees the exact prorated charge, then charged
 * to the saved card as a merchant-initiated payment and confirmed by webhook. A downgrade has no
 * charge and applies at the current period end.
 */

export function PlanChangeDialog({
  open,
  onClose,
  subscription,
  tier,
  savedCard,
}: {
  open: boolean
  onClose: () => void
  subscription: SubscriptionView
  tier: PlanTier | null
  savedCard: SavedCardView | null
}) {
  const quote = useUpgradeQuote()
  const upgrade = useUpgrade()
  const downgrade = useDowngrade()
  const { mutate: requestQuote } = quote
  const isUpgrade = tier !== null && tier.priceMinor > subscription.tier.priceMinor
  const tierId = tier?.id ?? null
  const subscriptionId = subscription.subscriptionId

  useEffect(() => {
    if (open && isUpgrade && tierId) requestQuote({ subscriptionId, planTierId: tierId })
  }, [open, isUpgrade, tierId, subscriptionId, requestQuote])

  if (!tier) return null
  const q = quote.data
  const done = upgrade.isSuccess || downgrade.isSuccess
  const failure = upgrade.isError ? upgrade.error : downgrade.isError ? downgrade.error : quote.isError ? quote.error : null
  const canConfirm = !done && (isUpgrade ? q !== undefined && savedCard !== null : true)
  const end = subscription.currentPeriodEnd ? formatBillingDate(subscription.currentPeriodEnd) : "the end of this period"

  let body: ReactNode = null
  if (upgrade.isSuccess && upgrade.data) {
    body = <PaymentProgress paymentId={upgrade.data.paymentId} />
  } else if (downgrade.isSuccess && downgrade.data) {
    body = (
      <p role="status" className="m-0 text-body-md text-on-surface">
        Scheduled. {tier.name} starts on{" "}
        {downgrade.data.currentPeriodEnd ? formatBillingDate(downgrade.data.currentPeriodEnd) : end}.
      </p>
    )
  } else if (!isUpgrade) {
    body = (
      <p className="m-0 text-body-md text-on-surface">
        {tier.name} starts on {end}. You keep {subscription.tier.name} until then, and nothing is charged now.
      </p>
    )
  } else if (quote.isPending) {
    body = (
      <p role="status" className="m-0 text-body-sm text-on-surface-variant">
        Working out the price…
      </p>
    )
  } else if (q) {
    body = savedCard ? (
      <p className="m-0 text-body-md text-on-surface">
        You pay <span className="text-data-md">{formatMoney(q.amountMinor, q.currency)}</span> now for the rest of this period,
        charged to {savedCard.brand} {savedCard.maskedPan}. The extra allowance is added straight away.
      </p>
    ) : (
      <p className="m-0 text-body-md text-on-surface">
        Upgrades are charged to a saved card. Buy a credit pack by card once and Lemely keeps the card for later charges.
      </p>
    )
  }

  const confirm = () =>
    isUpgrade ? upgrade.mutate({ subscriptionId, planTierId: tier.id }) : downgrade.mutate({ subscriptionId, planTierId: tier.id })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Change to ${tier.name}`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {done ? "Close" : "Not now"}
          </Button>
          {canConfirm ? (
            <Button variant="primary" loading={upgrade.isPending || downgrade.isPending} onClick={confirm}>
              {isUpgrade && q ? `Pay ${formatMoney(q.amountMinor, q.currency)} and upgrade` : "Schedule the change"}
            </Button>
          ) : null}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {body}
        {failure ? (
          <p role="alert" className="m-0 text-body-sm text-error">
            {billingFailureMessage(failure, "change your plan")}
          </p>
        ) : null}
      </div>
    </Modal>
  )
}
