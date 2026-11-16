import { useEffect, useRef, useState } from "react"
import type { ReviewSort } from "@/lib/teacherTypes"
import "./review.css"
import { SORT_OPTIONS, sortLabel } from "./reviewQueueModel"
import { Tick } from "./Tick"

export function SortMenu({ value, onChange }: { value: ReviewSort; onChange: (s: ReviewSort) => void }) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener("mousedown", onDoc)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDoc)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])
  useEffect(() => {
    if (open) wrap.current?.querySelector<HTMLElement>('[role="menuitemradio"]')?.focus()
  }, [open])
  const onMenuKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return
    e.preventDefault()
    const items = Array.from(wrap.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [])
    const i = items.indexOf(document.activeElement as HTMLElement)
    const next = e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length
    items[next]?.focus()
  }
  return (
    <div ref={wrap} className="relative flex flex-none">
      <button ref={triggerRef} type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-2 whitespace-nowrap rounded-[14px] bg-surface-container-lowest px-3 text-[13.5px] font-semibold shadow-[inset_0_0_0_1px_var(--color-outline)] hover:shadow-[inset_0_0_0_1px_var(--color-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11">
        <span>{sortLabel(value)}</span>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open ? (
        <div role="menu" aria-label="Sort answers" onKeyDown={onMenuKey} className="absolute end-0 top-[calc(100%+6px)] z-20 min-w-[180px] rounded-2xl bg-surface-container-lowest p-1.5 shadow-[var(--lm-rq-menu-shadow)]">
          {SORT_OPTIONS.map((o) => (
            <button key={o.value} type="button" role="menuitemradio" aria-checked={value === o.value} onClick={() => { onChange(o.value); setOpen(false); triggerRef.current?.focus() }} className="flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-[9px] text-start text-[14px] font-semibold hover:bg-primary-container aria-checked:bg-primary-container aria-checked:text-primary focus-visible:outline-2 focus-visible:outline-primary pointer-coarse:min-h-11">
              {o.label}
              <span className="ms-auto">{value === o.value ? <Tick size={16} /> : null}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
