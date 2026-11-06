import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { formatMoney } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { SavedCardView } from "@/lib/billingTypes"
import { useAddSeats, useReduceSeats, useSeatQuote } from "@/lib/hooks/useBillingApi"
import { invalidateTeam } from "@/lib/hooks/useTeamApi"
import { seatCountValidation, seatsWord } from "@/lib/teamModel"
import { PaymentProgress } from "@/portals/billing/PaymentProgress"

/*
 * Extra seats (spec §2.2, §5.4): adding charges the prorated price now on the saved card
 * (`…/seats/quote`, then `…/seats`, 202) and the seats renew with the plan; removing
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
}: {
  open: boolean
  onClose: () => void
  subscriptionId: string
  perSeatMinor: number | null
  savedCard: SavedCardView | null
}) {
  const [qty, setQty] = useState("1")
  const queryClient = useQueryClient()
  const quote = useSeatQuote()
  const add = useAddSeats()
  const q = quote.data
  const count = seatCountValidation(qty, MAX_ADD)
  const seats = count.ok ? count.seats : null
  const failure = add.isError ? add.error : quote.isError ? quote.error : null
  // The charge settles by webhook after the dialog has refreshed the team once, so the
  // capacity is read again when the teacher closes it.
  const close = () => {
    if (add.isSuccess) invalidateTeam(queryClient)
    onClose()
  }
  return (
    <Modal
      open={open}
      onClose={close}
      size="sm"
      title="Add seats"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={close}>{add.isSuccess ? "Close" : "Not now"}</Button>
          {add.isSuccess ? null : q && savedCard && seats !== null ? (
            <Button variant="primary" loading={add.isPending} onClick={() => add.mutate({ subscriptionId, seats })}>
              Pay {formatMoney(q.amountMinor, q.currency)} for {seatsWord(seats)}
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
        {add.isSuccess && add.data ? (
          <PaymentProgress paymentId={add.data.paymentId} />
        ) : (
          <>
            <Input
              label="How many seats"
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_ADD}
              hint={`Between 1 and ${MAX_ADD}.`}
              error={count.ok ? undefined : count.error}
              value={qty}
              onChange={(e) => {
                setQty(e.target.value)
                quote.reset()
              }}
            />
            {q && seats !== null ? (
              savedCard ? (
                <p role="status" className="m-0 text-body-md text-on-surface">
                  For {seatsWord(seats)} you pay <span className="text-data-md">{formatMoney(q.amountMinor, q.currency)}</span> now
                  for the rest of this period
                  {perSeatMinor !== null ? (
                    <>
                      , then <span className="text-data-md">{formatMoney(perSeatMinor, q.currency)}</span> per seat each period with
                      your plan
                    </>
                  ) : null}
                  . Charged to {savedCard.brand} {savedCard.maskedPan}.
                </p>
              ) : (
                <p role="status" className="m-0 text-body-md text-on-surface">
                  Seats are charged to a saved card. Buy a credit pack by card once and Lemely keeps the card for later charges.
                </p>
              )
            ) : null}
          </>
        )}
        {failure ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(failure, "add seats")}</p> : null}
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
