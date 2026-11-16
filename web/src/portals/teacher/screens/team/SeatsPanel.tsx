/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
/* Allowance shown as a share, never as units; a six-column table from xl and stacked cards below, one of them hidden at any width. Plan-inactive and every-seat-taken notices say what to do next. */
import { useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { ProgressBar } from "@/components/ui/progress-bar"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { formatBillingDate, formatPercent } from "@/lib/billingFormat"
import type { SeatRow, TeamView } from "@/lib/billingTypes"
import { removableExtraSeats, scopeSummary, seatCapParts, seatCapacityModel, seatStatusText } from "@/lib/teamModel"
import { AddSeatsDialog, ReduceSeatsDialog } from "./SeatCountDialogs"
import { RemoveSeatDialog, SeatEditorDialog } from "./SeatEditorDialog"

/* Seat capacity, extra seats and the per-seat list (spec §2.2, §4.4). */

/** This month's seat allowance as a share, never as units (allowance sizes are hidden). */
function SeatUse({ seat }: { seat: SeatRow }) {
  if (seat.meterFraction === null) return <span className="text-body-sm text-on-surface-variant">Not started</span>
  return (
    <div className="flex items-center gap-2">
      <ProgressBar
        value={Math.min(100, seat.meterFraction * 100)}
        ariaLabel={`${seat.studentName}'s seat use this month`}
        className="w-20 flex-none"
      />
      <span className="text-data-sm text-on-surface">{formatPercent(seat.meterFraction)}</span>
    </div>
  )
}

/** The overflow line, with the credit figures in the data face. */
function SeatCap({ seat }: { seat: SeatRow }) {
  const p = seatCapParts(seat)
  if (!p) return <>No overflow</>
  return (
    <>
      Up to <span className="text-data-sm">{p.limit}</span> of your credits {p.period} (<span className="text-data-sm">{p.used}</span> used)
    </>
  )
}

function SeatActions({
  seat,
  onEdit,
  onRemove,
  stacked = false,
}: {
  seat: SeatRow
  onEdit: () => void
  onRemove: () => void
  /** The small-screen card: full-size buttons, Edit as the clear primary action. */
  stacked?: boolean
}) {
  return (
    <div className="flex gap-2">
      <Button
        size={stacked ? "md" : "sm"}
        variant={stacked ? "secondary" : "ghost"}
        onClick={onEdit}
        aria-label={`Edit seat for ${seat.studentName}`}
      >
        Edit
      </Button>
      {seat.status === "active" ? (
        <Button size={stacked ? "md" : "sm"} variant="ghost" onClick={onRemove} aria-label={`Remove ${seat.studentName}`}>
          Remove
        </Button>
      ) : null}
    </div>
  )
}

export function SeatsPanel({ team }: { team: TeamView }) {
  const cap = seatCapacityModel(team)
  const { pathname } = useLocation()
  const [adding, setAdding] = useState(false)
  const [reducing, setReducing] = useState(false)
  // Held by id so the dialog always reads the current row after the list refreshes.
  const [editingId, setEditingId] = useState<string | null>(null)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const editing = team.seats.find((x) => x.memberId === editingId) ?? null
  const removing = team.seats.find((x) => x.memberId === removingId) ?? null
  const removable = removableExtraSeats(team)
  const reductionPending = team.pendingExtraSeats !== null
  const full = cap.capacity > 0 && cap.free === 0
  return (
    <section aria-labelledby="seats-heading" className="flex flex-col gap-4">
      <h2 id="seats-heading" className="m-0 text-display-sm text-on-surface">Student seats</h2>
      {!team.planActive ? (
        <p role="status" className="m-0 rounded-lg bg-surface-container-high p-4 text-body-sm text-on-surface">
          Your plan isn't active, so seats get no new monthly allowances. Students keep their seats.{" "}
          <Link to="/teacher/billing/plans" className="font-medium text-primary underline-offset-2 hover:underline">See plans</Link>
        </p>
      ) : null}
      <Card>
        <CardBody className="flex flex-col gap-3">
          <ProgressBar value={cap.barValue} label={cap.label} tone="accent" />
          <p className="m-0 text-body-sm text-on-surface-variant">{cap.detail}</p>
          {full ? (
            <p className="m-0 text-body-sm text-on-surface">
              Every seat is taken. {team.planActive ? "Add seats so more students can join." : "Students can't take a seat until you have a plan."}
            </p>
          ) : null}
          {team.pendingExtraSeats !== null && team.currentPeriodEnd ? (
            <p className="m-0 text-body-sm text-on-surface-variant">
              Drops to {team.pendingExtraSeats} extra {team.pendingExtraSeats === 1 ? "seat" : "seats"} on{" "}
              {formatBillingDate(team.currentPeriodEnd)}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => setAdding(true)} disabled={!team.planActive || team.subscriptionId === null}>Add seats</Button>
            {team.extraSeats > 0 && !reductionPending ? <Button variant="ghost" onClick={() => setReducing(true)}>Remove extra seats</Button> : null}
          </div>
        </CardBody>
      </Card>
      {team.seats.length === 0 ? (
        <p className="m-0 max-w-[65ch] text-body-md text-on-surface-variant">
          No students hold a seat yet. Students take a seat when they join one of your classes with its code.
        </p>
      ) : (
        <>
          <div className="hidden xl:block">
            <Table density="operate">
              <caption className="sr-only">Student seats</caption>
              <THead>
                <TR>
                  <TH>Student</TH>
                  <TH>Covers</TH>
                  <TH>This month</TH>
                  <TH>Overflow</TH>
                  <TH>Status</TH>
                  <TH><span className="sr-only">Actions</span></TH>
                </TR>
              </THead>
              <TBody>
                {team.seats.map((seat) => (
                  <TR key={seat.memberId}>
                    <TD className="whitespace-nowrap">{seat.studentName}</TD>
                    <TD>{scopeSummary(seat, team.subjects)}</TD>
                    <TD><SeatUse seat={seat} /></TD>
                    <TD><SeatCap seat={seat} /></TD>
                    <TD className="whitespace-nowrap">{seatStatusText(seat)}</TD>
                    <TD><SeatActions seat={seat} onEdit={() => setEditingId(seat.memberId)} onRemove={() => setRemovingId(seat.memberId)} /></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
          <ul aria-label="Student seats" className="m-0 grid list-none grid-cols-1 gap-3 p-0 md:grid-cols-2 xl:hidden">
            {team.seats.map((seat) => (
              <li
                key={seat.memberId}
                className="flex flex-col gap-3 rounded-lg border border-outline-variant bg-surface-container-lowest p-4"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-body-md font-medium text-on-surface">{seat.studentName}</span>
                  <span className="text-body-sm text-on-surface-variant">{seatStatusText(seat)}</span>
                </div>
                <p className="m-0 text-body-sm text-on-surface">{scopeSummary(seat, team.subjects)}</p>
                <div className="flex flex-col gap-1">
                  <span className="text-label text-on-surface-variant">This month</span>
                  <SeatUse seat={seat} />
                </div>
                <p className="m-0 text-body-sm text-on-surface-variant"><SeatCap seat={seat} /></p>
                <SeatActions stacked seat={seat} onEdit={() => setEditingId(seat.memberId)} onRemove={() => setRemovingId(seat.memberId)} />
              </li>
            ))}
          </ul>
        </>
      )}
      {team.subscriptionId && adding ? (
        <AddSeatsDialog
          open
          onClose={() => setAdding(false)}
          subscriptionId={team.subscriptionId}
          perSeatMinor={team.extraSeatPriceMinor}
          savedCard={team.savedCard}
          returnTo={pathname}
        />
      ) : null}
      {team.subscriptionId && reducing ? (
        <ReduceSeatsDialog
          open
          onClose={() => setReducing(false)}
          subscriptionId={team.subscriptionId}
          extraSeats={team.extraSeats}
          removable={removable}
        />
      ) : null}
      {editing ? <SeatEditorDialog key={editing.memberId} open onClose={() => setEditingId(null)} seat={editing} subjects={team.subjects} /> : null}
      {removing ? <RemoveSeatDialog key={removing.memberId} open onClose={() => setRemovingId(null)} seat={removing} /> : null}
    </section>
  )
}
