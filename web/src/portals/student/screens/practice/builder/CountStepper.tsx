/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 */
/* L4 · count stepper (the mock's `cnt` + `stepr`). The kit has no number stepper; `ui/stepper` is a wizard. */
import { COUNT_MAX, COUNT_MIN, stepCount } from "./builderModel"

const BTN =
  "grid size-11 place-items-center rounded-[14px] bg-primary-container text-xl font-bold text-primary disabled:opacity-45 disabled:cursor-not-allowed focus-visible:!rounded-[14px] focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

export function CountStepper({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex items-center justify-between text-[14px] font-semibold text-on-surface">
      <span id="count-label">Questions</span>
      <div className="flex items-center gap-3" role="group" aria-labelledby="count-label">
        <button type="button" aria-label="Fewer" className={BTN} disabled={value <= COUNT_MIN} onClick={() => onChange(stepCount(value, -1))}>
          −
        </button>
        {/* Mono, not the mock's display face: numbers are Mono, and Bricolage is not set below 28px. */}
        <span aria-live="polite" className="min-w-[2ch] text-center font-mono text-[26px] font-extrabold leading-none tabular-nums text-primary">
          {value}
        </span>
        <button type="button" aria-label="More" className={BTN} disabled={value >= COUNT_MAX} onClick={() => onChange(stepCount(value, 1))}>
          +
        </button>
      </div>
    </div>
  )
}
