import { useEffect, useRef, useState } from "react"
import type { ReviewQueueFilters } from "@/lib/reviewQueueQuery"
import "./review.css"
import { filterCategories, filterValues, type FilterCategory, type FilterOptions } from "./reviewQueueModel"
import { Tick } from "./Tick"

const ITEM = "flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-[9px] text-start text-[14px] font-semibold hover:bg-primary-container focus-visible:outline-2 focus-visible:outline-primary pointer-coarse:min-h-11"

export function FilterMenu({ filters, options, onToggle, onClose }: { filters: ReviewQueueFilters; options: FilterOptions; onToggle: (c: FilterCategory, v: string) => void; onClose: () => void }) {
  const [step, setStep] = useState<FilterCategory | null>(null)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    root.current?.querySelector<HTMLElement>("button")?.focus()
  }, [step])
  return (
    <div ref={root} role="menu" aria-label="Add a filter" onKeyDown={(e) => e.key === "Escape" && onClose()} className="absolute inset-x-0 top-[calc(100%+6px)] z-20 rounded-[18px] bg-surface-container-lowest p-2 shadow-[var(--lm-rq-menu-shadow)]">
      {step === null ? (
        <>
          <div className="px-2.5 pb-0.5 pt-1.5 font-mono text-[10.5px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">Filter by</div>
          {filterCategories(filters).map((c) => (
            <button key={c.key} type="button" role="menuitem" onClick={() => setStep(c.key)} className={ITEM}>
              {c.label}
              {c.count > 0 ? <span className="rounded-pill bg-primary px-[7px] py-px font-mono text-[11px] text-on-primary">{c.count}</span> : null}
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
              <span className={`inline-grid size-[18px] flex-none place-items-center rounded-[6px] text-on-primary ${v.checked ? "bg-primary" : "bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline)]"}`}>{v.checked ? <Tick size={12} /> : null}</span>
              {v.label}
            </button>
          ))}
        </>
      )}
    </div>
  )
}
