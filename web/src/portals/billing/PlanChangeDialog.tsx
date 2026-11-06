import { useEffect, useRef, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import { billingErrorCode, billingFailureMessage } from "@/lib/billingOutcome"
import type { PlanTier, SavedCardView, SubscriptionView } from "@/lib/billingTypes"
import { useDowngrade, useUpgrade, useUpgradeQuote } from "@/lib/hooks/useBillingApi"
import { PaymentProgress } from "./PaymentProgress"

/*
 * Upgrade now, downgrade at period end (spec §2.6, §5.3). An upgrade is quoted first
 * (`…/upgrade/quote`, no side effects) so the payer sees the exact prorated charge, then charged
 * to the saved card as a merchant-initiated payment and confirmed by webhook. A downgrade has no
 * charge and applies at the current period end.
 *
 * The mutations outlive a close, so every result is read only when it was made for the tier on
 * screen (`forTier`); the parent also keys this dialog by tier id so a new open starts clean.
 * One persistent `role="status"` line carries quoting, the quote and the scheduled result so
 * assistive tech announces changes to it; when a result replaces the confirm button, focus moves
 * to that result so it is not lost with the button.
 */

const STATUS_SHOWN = "m-0 text-body-md text-on-surface focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary"

/** A mutation result counts for this tier only; `undefined` variables means it has not run yet. */
function forTier(vars: { planTierId: string } | undefined, tierId: string): boolean {
  return vars === undefined || vars.planTierId === tierId
}

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
  const statusRef = useRef<HTMLParagraphElement>(null)
  const progressRef = useRef<HTMLDivElement>(null)
  const isUpgrade = tier !== null && tier.priceMinor > subscription.tier.priceMinor
  const tierId = tier?.id ?? null
  const subscriptionId = subscription.subscriptionId
  const hasCard = savedCard !== null

  // The quote exists to price the charge to the saved card; with no card there is nothing to charge.
  useEffect(() => {
    if (open && isUpgrade && tierId && hasCard) requestQuote({ subscriptionId, planTierId: tierId })
  }, [open, isUpgrade, tierId, hasCard, subscriptionId, requestQuote])

  const upgraded = tierId !== null && upgrade.isSuccess && forTier(upgrade.variables, tierId)
  const downgraded = tierId !== null && downgrade.isSuccess && forTier(downgrade.variables, tierId)
  const done = upgraded || downgraded

  // The confirm button unmounts when the change goes through; keep focus inside the dialog.
  useEffect(() => {
    if (upgraded) progressRef.current?.focus()
    else if (downgraded) statusRef.current?.focus()
  }, [upgraded, downgraded])

  if (!tier) return null
  const q = quote.isSuccess && forTier(quote.variables, tier.id) ? quote.data : undefined
  const upgradeFailed = upgrade.isError && forTier(upgrade.variables, tier.id)
  const downgradeFailed = downgrade.isError && forTier(downgrade.variables, tier.id)
  const quoteFailed = quote.isError && forTier(quote.variables, tier.id)
  const failure = upgradeFailed ? upgrade.error : downgradeFailed ? downgrade.error : quoteFailed ? quote.error : null
  // `downgrade_unavailable` says this plan cannot be scheduled right now, so offering the same button again would contradict it.
  const unavailable = downgradeFailed && billingErrorCode(downgrade.error) === "downgrade_unavailable"
  const canConfirm = !done && !unavailable && (isUpgrade ? q !== undefined && hasCard : true)
  const busy = upgrade.isPending || downgrade.isPending
  const end = subscription.currentPeriodEnd ? formatBillingDate(subscription.currentPeriodEnd) : "the end of this period"

  // What the persistent live line says right now, if anything.
  let status: ReactNode = null
  let statusClass = STATUS_SHOWN
  let body: ReactNode = null
  if (upgraded && upgrade.data) {
    body = (
      <div ref={progressRef} tabIndex={-1} className="focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary">
        <PaymentProgress paymentId={upgrade.data.paymentId} />
      </div>
    )
  } else if (downgraded && downgrade.data) {
    status = `Scheduled. ${tier.name} starts on ${
      downgrade.data.currentPeriodEnd ? formatBillingDate(downgrade.data.currentPeriodEnd) : end
    }.`
  } else if (!isUpgrade) {
    body = (
      <p className="m-0 text-body-md text-on-surface">
        {tier.name} starts on {end}. You keep {subscription.tier.name} until then, and nothing is charged now.
      </p>
    )
  } else if (!hasCard) {
    body = (
      <p className="m-0 text-body-md text-on-surface">
        Upgrades are charged to a saved card. Buy a credit pack by card once and Lemely keeps the card for later charges.
      </p>
    )
  } else if (quote.isPending) {
    status = "Working out the price…"
    statusClass = "m-0 text-body-sm text-on-surface-variant"
  } else if (q && savedCard) {
    status = (
      <>
        You pay <span className="text-data-md">{formatMoney(q.amountMinor, q.currency)}</span> now for the rest of this period,
        charged to {savedCard.brand} {savedCard.maskedPan}. The extra allowance is added straight away.
      </>
    )
  }

  const confirm = () =>
    isUpgrade ? upgrade.mutate({ subscriptionId, planTierId: tier.id }) : downgrade.mutate({ subscriptionId, planTierId: tier.id })

  return (
    <Modal
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title={`Change to ${tier.name}`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {done ? "Close" : "Not now"}
          </Button>
          {canConfirm ? (
            <Button variant="primary" loading={busy} onClick={confirm}>
              {isUpgrade && q ? `Pay ${formatMoney(q.amountMinor, q.currency)} and upgrade` : "Schedule the change"}
            </Button>
          ) : null}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {body}
        <p ref={statusRef} role="status" tabIndex={-1} className={status ? statusClass : "sr-only"}>
          {status}
        </p>
        <p role="alert" className={failure ? "m-0 text-body-sm text-error" : "sr-only"}>
          {failure ? billingFailureMessage(failure, "change your plan") : null}
        </p>
      </div>
    </Modal>
  )
}
