import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { Select } from "@/components/ui/select"
import { formatBillingDate } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { CapPeriod, MeteredAction, SeatRow } from "@/lib/billingTypes"
import { useRemoveSeat, useSetMemberCap, useSetSeatScope } from "@/lib/hooks/useTeamApi"
import { SEAT_ACTIONS, SEAT_ACTION_COPY } from "@/lib/teamModel"

/*
 * A seat's scope and overflow cap (spec §2.2). Subjects route work per subject; actions say
 * what the seat pays for. Weekly study plans are off unless the teacher turns them on.
 * The scope is enforced server-side; this dialog only edits it.
 */

const toggle = <T,>(list: T[], item: T, on: boolean) => (on ? [...new Set([...list, item])] : list.filter((x) => x !== item))

export function SeatEditorDialog({
  open,
  onClose,
  seat,
  subjects,
}: {
  open: boolean
  onClose: () => void
  seat: SeatRow
  subjects: { code: string; name: string }[]
}) {
  const scope = useSetSeatScope()
  const cap = useSetMemberCap()
  const [subjectCodes, setSubjectCodes] = useState<string[]>(seat.scopeSubjects)
  const [actions, setActions] = useState<MeteredAction[]>(seat.scopeActions)
  const [overflow, setOverflow] = useState(seat.capUnits !== null)
  const [capUnits, setCapUnits] = useState(String(seat.capUnits ?? 500))
  const [capPeriod, setCapPeriod] = useState<CapPeriod>(seat.capPeriod)
  const failure = scope.isError ? scope.error : cap.isError ? cap.error : null
  // A subject the seat already covers stays editable even when none of the teacher's
  // classes teach it any more, so it can always be switched off.
  const choices = [
    ...subjects,
    ...seat.scopeSubjects.filter((code) => !subjects.some((s) => s.code === code)).map((code) => ({ code, name: code })),
  ]

  const save = () =>
    scope.mutate(
      { memberId: seat.memberId, body: { subjects: subjectCodes, actions } },
      {
        onSuccess: () =>
          cap.mutate(
            {
              memberId: seat.memberId,
              body: { capUnits: overflow ? Math.max(1, Math.floor(Number(capUnits) || 1)) : null, capPeriod },
            },
            { onSuccess: onClose },
          ),
      },
    )

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Seat for ${seat.studentName}`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={scope.isPending || cap.isPending} onClick={save}>Save seat</Button>
        </div>
      }
    >
      <div className="flex flex-col gap-6">
        <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
          <legend className="mb-2 p-0 text-label text-on-surface">Subjects this seat covers</legend>
          {choices.length === 0 ? (
            <p className="m-0 text-body-sm text-on-surface-variant">
              Your classes don't have a subject yet. Add a subject to a class to choose what this seat covers.
            </p>
          ) : (
            choices.map((s) => (
              <Checkbox
                key={s.code}
                name="subjects"
                value={s.code}
                label={s.name}
                checked={subjectCodes.includes(s.code)}
                onChange={(e) => setSubjectCodes((l) => toggle(l, s.code, e.target.checked))}
              />
            ))
          )}
          {subjectCodes.length === 0 ? (
            <p className="m-0 text-body-sm text-on-surface-variant">With no subjects, this seat pays for nothing.</p>
          ) : null}
        </fieldset>
        <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
          <legend className="mb-2 p-0 text-label text-on-surface">What the seat pays for</legend>
          {SEAT_ACTIONS.map((a) => (
            <div key={a} className="flex flex-col gap-1">
              <Checkbox
                name="actions"
                value={a}
                label={SEAT_ACTION_COPY[a].label}
                checked={actions.includes(a)}
                onChange={(e) => setActions((l) => toggle(l, a, e.target.checked))}
              />
              {SEAT_ACTION_COPY[a].hint ? (
                <p className="m-0 ps-7 text-body-sm text-on-surface-variant">{SEAT_ACTION_COPY[a].hint}</p>
              ) : null}
            </div>
          ))}
        </fieldset>
        <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
          <legend className="mb-2 p-0 text-label text-on-surface">When the seat's monthly allowance runs out</legend>
          <Checkbox
            name="overflow"
            label="Let them use my credits"
            checked={overflow}
            onChange={(e) => setOverflow(e.target.checked)}
          />
          {overflow ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Input label="Up to (credits)" type="number" inputMode="numeric" min={1} value={capUnits} onChange={(e) => setCapUnits(e.target.value)} />
              <Select label="Counted" value={capPeriod} onChange={(e) => setCapPeriod(e.target.value === "total" ? "total" : "month")}>
                <option value="month">per month</option>
                <option value="total">in total</option>
              </Select>
            </div>
          ) : (
            <p className="m-0 text-body-sm text-on-surface-variant">No overflow. Their own plan or credits pay once the seat's allowance is used.</p>
          )}
        </fieldset>
        {failure ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(failure, "save this seat")}</p> : null}
      </div>
    </Modal>
  )
}

function monthEnd(now: Date): string {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0, 23, 59, 59)).toISOString()
}

export function RemoveSeatDialog({ open, onClose, seat }: { open: boolean; onClose: () => void; seat: SeatRow }) {
  const remove = useRemoveSeat()
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      title={`Remove ${seat.studentName}`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Keep seat</Button>
          <Button variant="primary" loading={remove.isPending} onClick={() => remove.mutate(seat.memberId, { onSuccess: onClose })}>
            Remove at month end
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="m-0 text-body-md text-on-surface">
          {seat.studentName} keeps the seat until {formatBillingDate(monthEnd(new Date()))}, then it frees up. Their current monthly
          allowance runs until it expires.
        </p>
        {remove.isError ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(remove.error, "remove this seat")}</p> : null}
      </div>
    </Modal>
  )
}
