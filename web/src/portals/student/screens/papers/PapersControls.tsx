/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V4 */
import { useId, useState, type ReactNode } from "react"
import { SlidersHorizontal } from "@phosphor-icons/react"
import {
  PERIODS,
  SORTS,
  activeFilterCount,
  type FilterOptions,
  type PapersFilters,
} from "./papersModel"
import "../subject/subject.css"
import "./papers.css"

function Choice<T extends string | number | null>({
  label,
  value,
  options,
  onPick,
}: {
  label: string
  value: T
  options: { key: T; text: ReactNode; name: string }[]
  onPick: (key: T) => void
}) {
  const id = useId()
  return (
    <div className="ap-group" role="group" aria-labelledby={id}>
      <span id={id} className="ap-label">
        {label}
      </span>
      <div className="ap-seg">
        {options.map((o) => (
          <button key={String(o.key)} type="button" aria-pressed={o.key === value} aria-label={`${label}: ${o.name}`} onClick={() => onPick(o.key)}>
            {o.text}
          </button>
        ))}
      </div>
    </div>
  )
}

/**
 * Filters (paper, variant, session, date) and the sort. A filter appears only when the data has more than one
 * value for it. On phone the whole set folds behind one button that shows how many are on; from 768px it sits open
 * beside the list.
 */
export function PapersControls({
  filters,
  options,
  onChange,
}: {
  filters: PapersFilters
  options: FilterOptions
  onChange: (next: PapersFilters) => void
}) {
  const active = activeFilterCount(filters)
  const [open, setOpen] = useState(active > 0)
  const panelId = useId()
  const all = { key: null, text: "All", name: "all" }
  return (
    <>
      <button type="button" className="ap-toggle ap-toggle--filters lm-press" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(!open)}>
        <span className="inline-flex items-center gap-2">
          <SlidersHorizontal size={18} weight="bold" aria-hidden="true" />
          Filter and sort
        </span>
        {active > 0 ? <b aria-label={`${active} on`}>{active}</b> : null}
      </button>
      <div id={panelId} className="ap-panel" data-open={open}>
        {options.papers.length > 0 ? (
          <Choice
            label="Paper"
            value={filters.paper}
            options={[all, ...options.papers.map((n) => ({ key: n, text: n, name: `paper ${n}` }))]}
            onPick={(paper) => onChange({ ...filters, paper })}
          />
        ) : null}
        {options.variants.length > 0 ? (
          <Choice
            label="Variant"
            value={filters.variant}
            options={[all, ...options.variants.map((n) => ({ key: n, text: n, name: `variant ${n}` }))]}
            onPick={(variant) => onChange({ ...filters, variant })}
          />
        ) : null}
        {options.sessions.length > 0 ? (
          <Choice
            label="Session"
            value={filters.session}
            options={[all, ...options.sessions.map((s) => ({ key: s, text: s, name: s }))]}
            onPick={(session) => onChange({ ...filters, session })}
          />
        ) : null}
        <Choice
          label="Date"
          value={filters.period}
          options={PERIODS.map((p) => ({ key: p.key, text: p.label, name: p.label }))}
          onPick={(period) => onChange({ ...filters, period })}
        />
        <Choice
          label="Sort"
          value={filters.sort}
          options={SORTS.map((s) => ({ key: s.key, text: s.label, name: s.label }))}
          onPick={(sort) => onChange({ ...filters, sort })}
        />
      </div>
    </>
  )
}
