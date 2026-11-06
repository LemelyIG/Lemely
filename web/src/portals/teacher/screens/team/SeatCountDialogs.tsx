import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { formatMoney } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { SavedCardView } from "@/lib/billingTypes"
import { useAddSeats, useReduceSeats, useSeatQuote } from "@/lib/hooks/useBillingApi"
import { PaymentProgress } from "@/portals/billing/PaymentProgress"

/*
 * Extra seats (spec §2.2, §5.4): adding charges the prorated price now on the saved card
 * (`…/seats/quote`, then `…/seats`, 202) and the seats renew with the plan; removing
 * schedules a lower total for the next renewal (`…/seats/pending`) and is refused while
 * it would leave fewer seats than seated students.
 *
 * Mounted only while open (see `SeatsPanel`), so every opening starts from a fresh quote.
 */

const clamp = (v: string, max: number) => Math.max(1, Math.min(max, Math.floor(Number(v) || 1)))

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
  const seats = clamp(qty, 100)
  const failure = add.isError ? add.error : quote.isError ? quote.error : null
  // The charge settles by webhook after the dialog has refreshed the team once, so the
  // capacity is read again when the teacher closes it.
  const close = () => {
    if (add.isSuccess) void queryClient.invalidateQueries({ queryKey: ["team"] })
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
          {add.isSuccess ? null : q && savedCard ? (
            <Button variant="primary" loading={add.isPending} onClick={() => add.mutate({ subscriptionId, seats })}>
              Pay {formatMoney(q.amountMinor, q.currency)} and add seats
            </Button>
          ) : q ? null : (
            <Button variant="primary" loading={quote.isPending} onClick={() => quote.mutate({ subscriptionId, seats })}>
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
              max={100}
              value={qty}
              onChange={(e) => {
                setQty(e.target.value)
                quote.reset()
              }}
            />
            {q ? (
              savedCard ? (
                <p role="status" className="m-0 text-body-md text-on-surface">
                  You pay <span className="text-data-md">{formatMoney(q.amountMinor, q.currency)}</span> now for the rest of this
                  period
                  {perSeatMinor !== null ? `, then ${formatMoney(perSeatMinor, q.currency)} per seat each period with your plan` : ""}.
                  Charged to {savedCard.brand} {savedCard.maskedPan}.
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
}: {
  open: boolean
  onClose: () => void
  subscriptionId: string
  extraSeats: number
}) {
  const [qty, setQty] = useState("1")
  const reduce = useReduceSeats()
  const pending = reduce.data?.pendingExtraSeats ?? null
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
              onClick={() => reduce.mutate({ subscriptionId, extraSeats: extraSeats - clamp(qty, extraSeats) })}
            >
              Remove at period end
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
        ) : (
          <>
            <p className="m-0 text-body-md text-on-surface">
              Seats you remove stay usable until the end of this period. You can't remove seats students still hold.
            </p>
            <Input label="How many seats" type="number" inputMode="numeric" min={1} max={extraSeats} value={qty} onChange={(e) => setQty(e.target.value)} />
          </>
        )}
        {reduce.isError ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(reduce.error, "remove seats")}</p> : null}
      </div>
    </Modal>
  )
}
