/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState } from "react"
import { Card, CardBody } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState } from "@/components/ui/state-views"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Modal } from "@/components/ui/modal"
import { activationDecisionFailureMessage, adminLoadFailureMessage } from "@/lib/adminOutcome"
import { useActivationQueue, useDecideActivation } from "@/lib/hooks/useAdminApi"
import type { PendingActivation } from "@/lib/adminTypes"
import { formatAdminDate } from "../data"

/**
 * X-02 · Account activation queue.
 *
 * Reads `GET /api/admin/activations`; writes through the two decision routes.
 * Payments are deferred, so activation is a person deciding, and this screen is
 * where they decide.
 *
 * ── Three things this screen does that a plainer queue would not ───────────
 *
 * **A decision needs a note before it can be made.** The column exists
 * (migration `0019`) precisely so a decision is auditable, and a queue where
 * the note is optional is a queue where it is empty. The API keeps it nullable
 * because a note has no honest default; the *screen* is where "please say why"
 * belongs, so the confirm button stays disabled until something is written.
 *
 * **Rejecting is not cancelling, and the copy says so.** The row lands on
 * `rejected`, a status that exists only because "we declined this" and "they
 * quit" are different events with different parties responsible.
 *
 * **A 409 is expected, not exceptional.** Two admins working one queue is the
 * ordinary case. The failure message says another decision already stands and
 * asks for a reload, rather than inviting a retry that cannot succeed.
 */
export function Activations() {
  const query = useActivationQueue()
  const [deciding, setDeciding] = useState<{ row: PendingActivation; activate: boolean } | null>(
    null,
  )

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>Platform admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Activations</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          Subscriptions waiting on a person. Payments are handled outside Lemely, so each of these
          is switched on or turned down by hand.
        </p>
      </header>

      <QueryState
        query={query}
        skeleton={
          <>
            <PageHeaderSkeleton />
            <ListSkeleton rows={3} />
          </>
        }
        error={{ heading: "We couldn't load the queue", body: adminLoadFailureMessage }}
        isEmpty={(data) => data.pending.length === 0}
        empty={
          <EmptyState
            marginalia="nothing waiting"
            heading="The queue is empty"
            body="Every subscription that has been requested has been decided. New requests appear here as they arrive, oldest first."
          />
        }
      >
        {(data) => (
          <div className="flex flex-col gap-3">
            {data.pending.map((row) => (
              <QueueRow
                key={row.subscriptionId}
                row={row}
                onDecide={(activate) => setDeciding({ row, activate })}
              />
            ))}
          </div>
        )}
      </QueryState>

      {deciding ? (
        <DecisionDialog
          row={deciding.row}
          activate={deciding.activate}
          onClose={() => setDeciding(null)}
        />
      ) : null}
    </div>
  )
}

/**
 * One request.
 *
 * The price is rendered from `priceMinor` and the plan's own `currency`,
 * divided once here rather than by the API. `Intl.NumberFormat` is given the
 * currency the row actually carries, so an EGP plan does not silently print a
 * dollar sign.
 */
function QueueRow({
  row,
  onDecide,
}: {
  row: PendingActivation
  onDecide: (activate: boolean) => void
}) {
  const price = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: row.currency,
  }).format(row.priceMinor / 100)

  return (
    <Card>
      <CardBody className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-body-md text-ink">{row.displayName ?? row.email}</span>
          <span className="text-body-sm text-ink-muted">
            {row.displayName ? `${row.email}, ` : ""}
            {row.role.replace(/_/g, " ")}
          </span>
          <span className="text-body-sm text-ink-muted">
            {row.planName} at <span className="tabular-nums">{price}</span>, asked for on{" "}
            <time dateTime={row.requestedAt} className="tabular-nums">
              {formatAdminDate(row.requestedAt)}
            </time>
          </span>
        </div>
        <div className="flex flex-none flex-wrap gap-2">
          <Button variant="primary" onClick={() => onDecide(true)}>
            Activate
          </Button>
          <Button onClick={() => onDecide(false)}>Turn down</Button>
        </div>
      </CardBody>
    </Card>
  )
}

/**
 * The note dialog, shared by both directions.
 *
 * One component rather than two because they are one decision with two
 * outcomes; the only thing that differs is the wording and which route runs.
 * `dismissible={false}` for the same reason every destructive confirmation in
 * this product carries it: a stray Escape must not answer on the reader's
 * behalf.
 */
function DecisionDialog({
  row,
  activate,
  onClose,
}: {
  row: PendingActivation
  activate: boolean
  onClose: () => void
}) {
  const [note, setNote] = useState("")
  const decide = useDecideActivation()
  const written = note.trim() !== ""

  return (
    <Modal
      open
      onClose={onClose}
      dismissible={false}
      title={activate ? "Activate this subscription?" : "Turn this request down?"}
      description={`${row.displayName ?? row.email} asked for ${row.planName}.`}
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="primary" onClick={onClose}>
            Go back
          </Button>
          <Button
            loading={decide.isPending}
            disabled={!written}
            onClick={() =>
              decide.mutate(
                { subscriptionId: row.subscriptionId, activate, note: note.trim() },
                { onSuccess: onClose },
              )
            }
          >
            {activate ? "Activate" : "Turn it down"}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-body-sm text-ink-muted">
          {activate
            ? "They get the plan straight away, and the decision is recorded against their subscription with your note."
            : "They keep their account and their work. Only this request is turned down, and they can ask again."}
        </p>

        <Textarea
          label="Why?"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={3}
          hint={
            activate
              ? "Whoever reads this row next sees only what you write here. A payment reference is usually enough."
              : "The reason is kept with the request so a later decision has something to go on."
          }
        />

        {!written ? (
          <p className="text-body-sm text-ink-faint">
            A note is needed before this can be recorded.
          </p>
        ) : null}

        {decide.isError ? (
          <p className="text-body-sm text-err">{activationDecisionFailureMessage(decide.error)}</p>
        ) : null}
      </div>
    </Modal>
  )
}
