import { Check } from "@phosphor-icons/react"

/** fc.css `.due`: Mono 800 18px primary over a 12px "due"; zero shows a success tick. */
export function DueCount({ due }: { due: number }) {
  if (due === 0) {
    return (
      <span className="grid min-w-11 justify-items-center text-success-text">
        <Check size={16} weight="bold" role="img" aria-label="Nothing due" />
      </span>
    )
  }
  return (
    <span className="grid min-w-11 justify-items-center font-mono text-[18px] font-extrabold leading-none text-primary">
      {due}
      <small className="mt-0.5 font-sans text-[12px] font-semibold text-on-surface-variant">due</small>
    </span>
  )
}
