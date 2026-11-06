import { ProgressBar } from "@/components/ui/progress-bar"
import type { UsageMeterView } from "@/lib/billingTypes"
import { allowanceMeterModel, seatMeterModel, type MeterModel } from "@/lib/usageMeterModel"

/*
 * The usage meter (spec §2.1: "Usage 63%, resets 14 Nov"). Allowances are shown only as a
 * share of the plan, never in units: allowance sizes are hidden by design.
 */

function MeterRow({ model }: { model: MeterModel }) {
  return (
    <div className="flex flex-col gap-1.5" data-state={model.state}>
      <ProgressBar value={model.barValue} label={model.label} />
      {model.note ? <p className="m-0 text-body-sm text-on-surface-variant">{model.note}</p> : null}
    </div>
  )
}

export function UsageMeterCard({ meter }: { meter: UsageMeterView }) {
  const hasAny = meter.allowance !== null || meter.seats.length > 0
  return (
    <section
      aria-labelledby="usage-meter-heading"
      className="flex flex-col gap-4 rounded-lg border border-outline-variant bg-surface-container-lowest p-5"
    >
      <h2 id="usage-meter-heading" className="m-0 text-display-sm text-on-surface">
        Usage
      </h2>
      {meter.allowance ? <MeterRow model={allowanceMeterModel(meter.allowance)} /> : null}
      {meter.seats.map((seat) => (
        <MeterRow key={seat.teacherMemberId} model={seatMeterModel(seat)} />
      ))}
      {hasAny ? null : (
        <p className="m-0 text-body-sm text-on-surface-variant">No plan allowance. Usage comes from your credits.</p>
      )}
    </section>
  )
}
