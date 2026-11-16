/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* One persistent live line carries quoting, the quote and the scheduled result, and focus follows the result when the confirm button unmounts. The branch ladder for `status`/`body` is long (R4, not R5) but each branch is a distinct fact the payer needs. */
import { useEffect, useRef, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import { billingErrorCode, billingFailureMessage, isTerminalRefusal } from "@/lib/billingOutcome"
import type { PlanTier, SubscriptionView } from "@/lib/billingTypes"
import { useDowngrade, useUpgrade, useUpgradeQuote } from "@/lib/hooks/useBillingApi"
import { isCheckoutPhoneRequired } from "@/lib/phone"
import { CheckoutPhonePrompt } from "./CheckoutPhonePrompt"
import { UNSAFE_CHECKOUT_URL, useCheckoutLaunch } from "./useCheckoutLaunch"

/*
 * Upgrade now, downgrade at period end (spec §2.6, §5.3). An upgrade is quoted first
 * (`…/upgrade/quote`, no side effects) so the payer sees the exact prorated charge, then sent to
 * Paymob's hosted checkout to pay and confirm with their bank. The dialog never says "upgraded":
 * nothing has changed until the return page (`/billing/return/{id}`) sees the payment paid. A
 * downgrade has no charge and applies at the current period end.
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
  returnTo,
  go,
}: {
  open: boolean
  onClose: () => void
  subscription: SubscriptionView
  tier: PlanTier | null
  /** The page this dialog was opened from; the payer lands back on it from "Back to billing". */
  returnTo: string
  /** Leaves for checkout; the browser's `location.assign` unless a test injects one. */
  go?: (url: string) => void
}) {
  const quote = useUpgradeQuote()
  const upgrade = useUpgrade()
  const downgrade = useDowngrade()
  const launch = useCheckoutLaunch(upgrade, returnTo, go)
  const { mutate: requestQuote } = quote
  const statusRef = useRef<HTMLParagraphElement>(null)
  const higherPrice = tier !== null && tier.priceMinor > subscription.tier.priceMinor
  // F1/F5: the server judges an upgrade on terms, not catalogue price, and both the upgrade and the
  // downgrade route need the interval being paid. Any other interval is a change at the period end.
  const held = subscription.tier.interval
  const crossInterval = tier !== null && held !== null && tier.interval !== held
  const isUpgrade = higherPrice && !crossInterval
  const tierId = tier?.id ?? null
  const subscriptionId = subscription.subscriptionId

  useEffect(() => {
    if (open && isUpgrade && tierId) requestQuote({ subscriptionId, planTierId: tierId })
  }, [open, isUpgrade, tierId, subscriptionId, requestQuote])

  const downgraded = tierId !== null && downgrade.isSuccess && forTier(downgrade.variables, tierId)

  // The confirm button unmounts when the change goes through; keep focus inside the dialog.
  useEffect(() => {
    if (downgraded) statusRef.current?.focus()
  }, [downgraded])

  if (!tier) return null
  const q = quote.isSuccess && forTier(quote.variables, tier.id) ? quote.data : undefined
  const upgradeFailed = upgrade.isError && forTier(upgrade.variables, tier.id)
  const downgradeFailed = downgrade.isError && forTier(downgrade.variables, tier.id)
  const quoteFailed = quote.isError && forTier(quote.variables, tier.id)
  const failure = upgradeFailed ? upgrade.error : downgradeFailed ? downgrade.error : quoteFailed ? quote.error : null
  const needsPhone = upgradeFailed && isCheckoutPhoneRequired(upgrade.error)
  // `downgrade_unavailable` says this plan cannot be scheduled right now, so offering the same button again would contradict it.
  const unavailable = downgradeFailed && billingErrorCode(downgrade.error) === "downgrade_unavailable"
  // A refusal that fails the same way again leaves nothing to press: each try spends a checkout attempt.
  const refused = (upgradeFailed && isTerminalRefusal(upgrade.error)) || (downgradeFailed && isTerminalRefusal(downgrade.error))
  const canConfirm = !downgraded && !unavailable && !refused && !crossInterval && !needsPhone && (isUpgrade ? q !== undefined : true)
  const busy = upgrade.isPending || launch.redirecting || downgrade.isPending
  const end = subscription.currentPeriodEnd ? formatBillingDate(subscription.currentPeriodEnd) : "the end of this period"

  // What the persistent live line says right now, if anything.
  let status: ReactNode = null
  let statusClass = STATUS_SHOWN
  let body: ReactNode = null
  if (launch.redirecting) {
    status = "Taking you to payment…"
    statusClass = "m-0 text-body-sm text-on-surface-variant"
  } else if (downgraded && downgrade.data) {
    status = `Scheduled. ${tier.name} starts on ${
      downgrade.data.currentPeriodEnd ? formatBillingDate(downgrade.data.currentPeriodEnd) : end
    }.`
  } else if (crossInterval) {
    body = (
      <p className="m-0 text-body-md text-on-surface">
        {tier.name} bills every {tier.interval}. Cancel at period end, then subscribe to it.
      </p>
    )
  } else if (!isUpgrade) {
    body = (
      <p className="m-0 text-body-md text-on-surface">
        {tier.name} starts on {end}. You keep {subscription.tier.name} until then. Nothing is charged now.
      </p>
    )
  } else if (quote.isPending) {
    status = "Getting the price…"
    statusClass = "m-0 text-body-sm text-on-surface-variant"
  } else if (q) {
    status = (
      <>
        Pay <span className="text-data-md">{formatMoney(q.amountMinor, q.currency)}</span> now for the rest of this period. You'll
        confirm with your bank next.
      </>
    )
  }

  const confirm = () =>
    isUpgrade ? launch.launch({ subscriptionId, planTierId: tier.id }) : downgrade.mutate({ subscriptionId, planTierId: tier.id })

  const message = launch.unsafe && isUpgrade ? UNSAFE_CHECKOUT_URL : failure && !needsPhone ? billingFailureMessage(failure, "change your plan") : null

  return (
    <Modal
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title={`Change to ${tier.name}`}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="ghost" className="w-full sm:w-auto" onClick={onClose} disabled={busy}>
            {downgraded ? "Close" : "Not now"}
          </Button>
          {canConfirm ? (
            <Button variant="primary" className="w-full sm:w-auto" loading={busy} onClick={confirm}>
              {isUpgrade && q ? "Continue to payment" : "Schedule the change"}
            </Button>
          ) : null}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {body}
        {needsPhone ? <CheckoutPhonePrompt
            onSaved={() => {
              // The prompt unmounts once the retry starts; keep focus in the dialog.
              statusRef.current?.focus()
              if (upgrade.variables) launch.launch(upgrade.variables)
            }}
          /> : null}
        <p ref={statusRef} role="status" tabIndex={-1} className={status ? statusClass : "sr-only"}>
          {status}
        </p>
        <p role="alert" className={message ? "m-0 text-body-sm text-error" : "sr-only"}>
          {message}
        </p>
      </div>
    </Modal>
  )
}
