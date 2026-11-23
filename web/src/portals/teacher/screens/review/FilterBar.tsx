/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useEffect, useRef, useState } from "react"
import type { ReviewQueueFilters } from "@/lib/reviewQueueQuery"
import type { ReviewSort } from "@/lib/teacherTypes"
import { FilterMenu } from "./FilterMenu"
import "./review.css"
import { filterChips, type FilterCategory, type FilterOptions } from "./reviewQueueModel"
import { SortMenu } from "./SortMenu"

export interface FilterBarProps {
  filters: ReviewQueueFilters
  options: FilterOptions
  shownLine: string | null
  onSearch: (q: string) => void
  onSort: (s: ReviewSort) => void
  onToggle: (c: FilterCategory, v: string) => void
  onRemove: (c: FilterCategory, v: string) => void
  searchRef: React.RefObject<HTMLInputElement | null>
}

export function FilterBar(p: FilterBarProps) {
  const [q, setQ] = useState(p.filters.q)
  const [menuOpen, setMenuOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const closeMenu = () => {
    setMenuOpen(false)
    triggerRef.current?.focus()
  }
  useEffect(() => setQ(p.filters.q), [p.filters.q])
  useEffect(() => {
    if (q === p.filters.q) return
    const t = window.setTimeout(() => p.onSearch(q), 250)
    return () => window.clearTimeout(t)
  }, [q]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!menuOpen) return
    const onDoc = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [menuOpen])
  const chips = filterChips(p.filters, p.options)
  return (
    <div className="grid min-w-0 gap-2">
      <div className="flex min-w-0 gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-button bg-surface-container-lowest px-3 text-on-surface-variant shadow-[inset_0_0_0_1px_var(--color-outline)] focus-within:shadow-[inset_0_0_0_1.5px_var(--color-primary),0_0_0_3px_var(--color-primary-container)]">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.5" /><path d="m10.5 10.5 3 3" /></svg>
          <input ref={p.searchRef} type="search" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && p.onSearch(q)} placeholder="Search" aria-label="Search students, papers or questions" className="w-full min-w-0 flex-1 border-0 bg-transparent py-2.5 text-sm font-semibold text-on-surface caret-primary outline-transparent" />
          <span className="rounded-bar bg-surface-container-high pointer-coarse:hidden px-1.5 py-px font-mono text-xs" aria-hidden="true">/</span>
        </label>
        <SortMenu value={p.filters.sort} onChange={p.onSort} />
      </div>
      <div ref={wrap} className="relative min-w-0">
        <div className="rq-chips flex flex-wrap items-center gap-1.5 pointer-coarse:gap-y-3.5">
          {chips.map((c) => (
            <span key={`${c.category}|${c.value}`} className="inline-flex items-center gap-1.5 rounded-pill bg-primary-container py-[3px] pe-1 ps-2.5 text-dense-sm font-semibold text-primary">
              {c.label}
              <button type="button" aria-label={`Remove ${c.label}`} onClick={() => p.onRemove(c.category, c.value)} className="relative inline-grid size-[18px] place-items-center rounded-pill bg-surface-container-lowest focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary after:absolute after:-inset-[3px] after:content-[''] pointer-coarse:after:-inset-[13px]">×</button>
            </span>
          ))}
          <button ref={triggerRef} type="button" aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)} className="relative rounded-pill border-[1.5px] border-dashed border-outline transition-colors motion-reduce:transition-none px-3 py-[3px] text-dense-sm font-semibold text-on-surface-variant hover:border-primary hover:text-primary focus-visible:outline-2 focus-visible:outline-primary after:absolute after:-inset-y-[3px] after:inset-x-0 after:content-[''] pointer-coarse:after:-inset-y-[10px]">+ Filter</button>
        </div>
        {menuOpen ? <FilterMenu filters={p.filters} options={p.options} onToggle={p.onToggle} onClose={closeMenu} /> : null}
      </div>
      {p.shownLine ? <div className="text-dense text-on-surface-variant" role="status">{p.shownLine}</div> : null}
    </div>
  )
}
