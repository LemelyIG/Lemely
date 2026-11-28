/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 */
import { Minus, Plus } from "@phosphor-icons/react"
import { useId } from "react"

/** fc.css `.cnt` + t.css `.stepr`: label left; − value + right; 44px buttons, Bricolage 26px value. */
export function CountStepper({
  value, onChange, min, max, label,
}: { value: number; onChange: (n: number) => void; min: number; max: number; label: string }) {
  const labelId = useId()
  return (
    <div className="flex items-center justify-between text-[14px] font-semibold leading-tight text-on-surface">
      <span id={labelId}>{label}</span>
      <div className="flex items-center gap-3" role="group" aria-labelledby={labelId}>
        <button type="button" aria-label="Fewer" aria-disabled={value <= min || undefined} onClick={() => value > min && onChange(value - 1)}
          className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary aria-disabled:opacity-40 focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary">
          <Minus size={18} weight="bold" aria-hidden />
        </button>
        <output aria-live="polite" className="min-w-[2ch] text-center font-display text-[26px] font-extrabold leading-none text-primary">
          {value}
        </output>
        <button type="button" aria-label="More" aria-disabled={value >= max || undefined} onClick={() => value < max && onChange(value + 1)}
          className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary aria-disabled:opacity-40 focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary">
          <Plus size={18} weight="bold" aria-hidden />
        </button>
      </div>
    </div>
  )
}
