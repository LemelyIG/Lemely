/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useRef, useState } from "react"
import { GitDiff } from "@phosphor-icons/react"
import type { PaperHistoryRow } from "@/lib/studentTypes"
import { AllPapersList } from "./AllPapersList"
import { ComparePanel } from "./ComparePanel"
import { PapersControls } from "./PapersControls"
import {
  DEFAULT_FILTERS,
  applyFilters,
  compareView,
  filterOptions,
  papersMode,
  prunePicks,
  rowViews,
  toggleSelected,
  type PapersFilters,
} from "./papersModel"
import "../subject/subject.css"
import "./papers.css"

/**
 * The loaded list. One attempt is a plain row and a sentence that a trend needs a second; two or more add the
 * filters, the sort and the compare mode beside the list.
 */
export function PapersBody({
  history,
  filters,
  onFilters,
  now,
}: {
  history: PaperHistoryRow[]
  filters: PapersFilters
  onFilters: (next: PapersFilters) => void
  now: Date
}) {
  const [comparing, setComparing] = useState(false)
  const [picks, setPicks] = useState<string[]>([])
  const panelRef = useRef<HTMLDivElement>(null)
  const shown = applyFilters(history, filters, now)
  const held = prunePicks(picks, shown)
  const compared = comparing ? compareView(history, held, now) : null
  // On a phone the panel sits above the list, so the second pick would complete off screen. Bring it into view.
  const comparedKey = compared ? `${compared.earlier.id}:${compared.later.id}` : null
  useEffect(() => {
    if (comparedKey) panelRef.current?.scrollIntoView({ block: "nearest" })
  }, [comparedKey])

  if (papersMode(history.length) === "single") {
    return (
      <div className="ap-main">
        <AllPapersList rows={rowViews(history, now)} picks={null} onPick={() => undefined} label="Papers" />
        <p className="sj-hint">One paper so far. Your trend starts with the next one.</p>
      </div>
    )
  }

  // Picks follow the rows on screen: changing a filter drops the ones it hides.
  const changeFilters = (next: PapersFilters) => {
    onFilters(next)
    setPicks((p) => prunePicks(p, applyFilters(history, next, now)))
  }
  const stopComparing = () => {
    setComparing(false)
    setPicks([])
  }
  return (
    <div className="ap-layout">
      <div className="ap-aside">
        <PapersControls filters={filters} options={filterOptions(history)} onChange={changeFilters} />
        <button
          type="button"
          className="ap-toggle ap-toggle--compare lm-press"
          aria-pressed={comparing}
          onClick={() => (comparing ? stopComparing() : setComparing(true))}
        >
          <span className="inline-flex items-center gap-2">
            <GitDiff size={18} weight="bold" aria-hidden="true" />
            Compare two
          </span>
        </button>
        {comparing ? (
          <div ref={panelRef}>
            <ComparePanel view={compared} picked={held.length} />
          </div>
        ) : null}
      </div>
      <div className="ap-main">
        <p className="sj-hint ap-count" role="status">
          <span className="ap-num">{shown.length}</span> of <span className="ap-num">{history.length}</span> papers
        </p>
        {shown.length > 0 ? (
          <AllPapersList
            rows={rowViews(shown, now)}
            picks={comparing ? held : null}
            onPick={(id) => setPicks((p) => toggleSelected(prunePicks(p, shown), id))}
            label={comparing ? "Papers, pick two to compare" : "Papers"}
          />
        ) : (
          <>
            <p className="sj-hint">No papers match these filters.</p>
            <button type="button" className="ap-clear" onClick={() => changeFilters(DEFAULT_FILTERS)}>
              Clear filters
            </button>
          </>
        )}
      </div>
    </div>
  )
}
