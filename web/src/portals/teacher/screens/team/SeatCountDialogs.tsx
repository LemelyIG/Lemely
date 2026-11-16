/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* The count is never coerced: an out-of-range value shows a field error and the quote and pay buttons stay disabled, so the seats priced are the seats charged. */
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { formatMoney } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { SavedCardView } from "@/lib/billingTypes"
import { useAddSeats, useReduceSeats, useSeatQuote } from "@/lib/hooks/useBillingApi"
import { isCheckoutPhoneRequired } from "@/lib/phone"
import { seatCountValidation, seatsWord } from "@/lib/teamModel"
import { CheckoutPhonePrompt } from "@/portals/billing/CheckoutPhonePrompt"
import { UNSAFE_CHECKOUT_URL, useCheckoutLaunch } from "@/portals/billing/useCheckoutLaunch"

/*
 * Extra seats (spec §2.2, §5.4): adding quotes the prorated price (`…/seats/quote`), then sends
 * the payer to Paymob's hosted checkout (`…/seats`, 201) and the seats renew with the plan. The
 * dialog never says "added": the seats exist once the return page sees the payment paid. Removing
 * schedules a lower total for the next renewal (`…/seats/pending`) and is refused while
 * it would leave fewer seats than seated students.
 *
 * The count is never coerced: an out-of-range or blank value shows a field error and the
 * quote and pay buttons stay disabled, so the seats quoted and charged are the seats typed.
 * Mounted only while open (see `SeatsPanel`), so every opening starts from a fresh quote.
 */

const MAX_ADD = 100

export function AddSeatsDialog({
  open,
  onClose,
  subscriptionId,
  perSeatMinor,
  savedCard,
  returnTo,
  go,
}: {
  open: boolean
  onClose: () => void
  subscriptionId: string
  perSeatMinor: number | null
  /** Offered on Paymob's page when the teacher has one; never required. */
  savedCard: SavedCardView | null
  /** The team page; "Back to your team" on the return page lands here. */
  returnTo: string
  /** Leaves for checkout; the browser's `location.assign` unless a test injects one. */
  go?: (url: string) => void
}) {
  const [qty, setQty] = useState("1")
  const quote = useSeatQuote()
  const add = useAddSeats()
  const launch = useCheckoutLaunch(add, returnTo, go)
  const q = quote.data
  const count = seatCountValidation(qty, MAX_ADD)
  const seats = count.ok ? count.seats : null
  const needsPhone = add.isError && isCheckoutPhoneRequired(add.error)
  const failure = add.isError ? add.error : quote.isError ? quote.error : null
  const busy = add.isPending || launch.redirecting
  const message = launch.unsafe ? UNSAFE_CHECKOUT_URL : failure && !needsPhone ? billingFailureMessage(failure, "add seats") : null
  return (
    <Modal
      open={open}
      onClose={onClose}
      dismissible={!busy}
      size="sm"
      title="Add seats"
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Not now</Button>
          {q && seats !== null && !needsPhone ? (
            <Button variant="primary" loading={busy} onClick={() => launch.launch({ subscriptionId, seats })}>
              Continue to payment ({formatMoney(q.amountMinor, q.currency)})
            </Button>
          ) : q ? null : (
            <Button
              variant="primary"
              loading={quote.isPending}
              disabled={seats === null}
              onClick={() => seats !== null && quote.mutate({ subscriptionId, seats })}
            >
              Get the price
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <Input
          label="How many seats"
          type="number"
          inputMode="numeric"
          min={1}
          max={MAX_ADD}
          hint={`Between 1 and ${MAX_ADD}.`}
          error={count.ok ? undefined : count.error}
          disabled={busy}
          value={qty}
          onChange={(e) => {
            setQty(e.target.value)
            quote.reset()
            add.reset()
          }}
        />
        {needsPhone ? <CheckoutPhonePrompt onSaved={() => add.variables && launch.launch(add.variables)} /> : null}
        {q && seats !== null && !needsPhone ? (
          <p role="status" className="m-0 text-body-md text-on-surface">
            {launch.redirecting ? (
              "Taking you to the payment page…"
            ) : (
              <>
                For {seatsWord(seats)} you pay <span className="text-data-md">{formatMoney(q.amountMinor, q.currency)}</span> now for
                the rest of this period
                {perSeatMinor !== null ? (
                  <>
                    , then <span className="text-data-md">{formatMoney(perSeatMinor, q.currency)}</span> per seat each period with your
                    plan
                  </>
                ) : null}
                . You&apos;ll confirm it with your bank on the next page.
                {savedCard ? ` Your saved card (${savedCard.brand} ${savedCard.maskedPan}) will be offered there.` : ""}
              </>
            )}
          </p>
        ) : null}
        {message ? <p role="alert" className="m-0 text-body-sm text-error">{message}</p> : null}
      </div>
    </Modal>
  )
}

export function ReduceSeatsDialog({
  open,
  onClose,
  subscriptionId,
  extraSeats,
  removable,
}: {
  open: boolean
  onClose: () => void
  subscriptionId: string
  extraSeats: number
  /** Most seats that can go: `min(extra seats, free seats)` (`removableExtraSeats`). */
  removable: number
}) {
  const [qty, setQty] = useState("1")
  const reduce = useReduceSeats()
  const pending = reduce.data?.pendingExtraSeats ?? null
  const count = seatCountValidation(qty, removable)
  const seats = count.ok ? count.seats : null
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      title="Remove extra seats"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>{reduce.isSuccess ? "Close" : "Not now"}</Button>
          {reduce.isSuccess ? null : (
            <Button
              variant="primary"
              loading={reduce.isPending}
              disabled={seats === null || removable < 1}
              onClick={() => seats !== null && reduce.mutate({ subscriptionId, extraSeats: extraSeats - seats })}
            >
              {seats === null ? "Remove seats" : `Remove ${seatsWord(seats)}`} at period end
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {reduce.isSuccess && pending !== null ? (
          <p role="status" className="m-0 text-body-md text-on-surface">
            {pending} extra {pending === 1 ? "seat" : "seats"} from the end of this period.
          </p>
        ) : removable < 1 ? (
          <p className="m-0 text-body-md text-on-surface">
            Students hold every seat you could remove. A removed student&apos;s seat frees up at the end of the month, then you can
            remove it here.
          </p>
        ) : (
          <>
            <p className="m-0 text-body-md text-on-surface">
              Seats you remove stay usable until the end of this period. You can&apos;t remove seats students still hold.
            </p>
            <Input
              label="How many seats"
              type="number"
              inputMode="numeric"
              min={1}
              max={removable}
              hint={`Up to ${removable} can go.`}
              error={count.ok ? undefined : count.error}
              value={qty}
              onChange={(e) => setQty(e.target.value)}
            />
          </>
        )}
        {reduce.isError ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(reduce.error, "remove seats")}</p> : null}
      </div>
    </Modal>
  )
}
