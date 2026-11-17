import { Minus, Plus } from "@phosphor-icons/react"
import { useId } from "react"

/** fc.css `.cnt` + t.css `.stepr`: label left; − value + right; 44px buttons, Bricolage 26px value. */
export function CountStepper({
  value, onChange, min, max, label,
}: { value: number; onChange: (n: number) => void; min: number; max: number; label: string }) {
  const labelId = useId()
  return (
    <div className="flex items-center justify-between text-[14px] font-semibold text-on-surface">
      <span id={labelId}>{label}</span>
      <div className="flex items-center gap-3" role="group" aria-labelledby={labelId}>
        <button type="button" aria-label="Fewer" disabled={value <= min} onClick={() => onChange(value - 1)}
          className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary disabled:opacity-40">
          <Minus size={18} weight="bold" aria-hidden />
        </button>
        <output aria-live="polite" className="min-w-[2ch] text-center font-display text-[26px] font-extrabold leading-none text-primary">
          {value}
        </output>
        <button type="button" aria-label="More" disabled={value >= max} onClick={() => onChange(value + 1)}
          className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary disabled:opacity-40">
          <Plus size={18} weight="bold" aria-hidden />
        </button>
      </div>
    </div>
  )
}
