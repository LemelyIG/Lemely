/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { useEffect, useRef, useState } from "react"
import type { ReviewQueueFilters } from "@/lib/reviewQueueQuery"
import "./review.css"
import { filterCategories, filterValues, type FilterCategory, type FilterOptions } from "./reviewQueueModel"
import { Tick } from "./Tick"

const ITEM = "flex w-full items-center gap-2.5 rounded-row px-2.5 py-[9px] text-start text-sm font-semibold hover:bg-primary-container focus-visible:outline-2 focus-visible:outline-primary pointer-coarse:min-h-11"

export function FilterMenu({ filters, options, onToggle, onClose }: { filters: ReviewQueueFilters; options: FilterOptions; onToggle: (c: FilterCategory, v: string) => void; onClose: () => void }) {
  const [step, setStep] = useState<FilterCategory | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const items = () => Array.from(root.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])
  useEffect(() => {
    const all = items()
    // Step 2 opens on the first value, not on the "back" item.
    ;(step === null ? all[0] : (all[1] ?? all[0]))?.focus()
  }, [step])
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") return onClose()
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return
    e.preventDefault()
    const all = items()
    const i = all.indexOf(document.activeElement as HTMLElement)
    all[e.key === "ArrowDown" ? (i + 1) % all.length : (i - 1 + all.length) % all.length]?.focus()
  }
  return (
    <div ref={root} role="menu" aria-label="Add a filter" onKeyDown={onKey} className="absolute inset-x-0 top-[calc(100%+6px)] z-dropdown rounded-inner bg-surface-container-lowest p-2 shadow-[var(--rq-menu-shadow)]">
      {step === null ? (
        <>
          <div className="px-2.5 pb-0.5 pt-1.5 font-mono text-xs font-semibold uppercase tracking-[0.08em] text-on-surface-variant">Filter by</div>
          {filterCategories(filters).map((c) => (
            <button key={c.key} type="button" role="menuitem" onClick={() => setStep(c.key)} className={ITEM}>
              {c.label}
              {c.count > 0 ? <span className="rounded-pill bg-primary px-[7px] py-px font-mono text-xs text-on-primary">{c.count}</span> : null}
              <span className="ms-auto text-on-surface-variant" aria-hidden="true">›</span>
            </button>
          ))}
        </>
      ) : (
        <>
          <button type="button" role="menuitem" onClick={() => setStep(null)} className={ITEM}>
            ‹ {filterCategories(filters).find((c) => c.key === step)?.label}
          </button>
          {filterValues(step, filters, options).map((v) => (
            <button key={v.value} type="button" role="menuitemcheckbox" aria-checked={v.checked} onClick={() => onToggle(step, v.value)} className={ITEM}>
              <span className={`inline-grid size-[18px] flex-none place-items-center rounded-bar text-on-primary ${v.checked ? "bg-primary" : "bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline)]"}`}>{v.checked ? <Tick size={12} /> : null}</span>
              {v.label}
            </button>
          ))}
        </>
      )}
    </div>
  )
}
