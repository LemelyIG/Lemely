/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useLayoutEffect, useRef } from "react"
import type { ReviewQueueFilters } from "@/lib/reviewQueueQuery"
import type { ReviewQueueItem } from "@/lib/teacherTypes"
import { FilterBar } from "./FilterBar"
import { QueueHeader } from "./QueueHeader"
import { QueueRow } from "./QueueRow"
import { Cleared, FirstRun, NoMatch, NothingWaiting, QueueLoading, SparseNote } from "./QueueStates"
import "./review.css"
import type { QueryStateQuery } from "@/components/ui/query-state"
import { clearFilters, focusAfterPagingEnds, removeFilter, toggleFilter, type FilterOptions, type QueueScreenState, type Tally } from "./reviewQueueModel"

export interface QueueColumnProps {
  state: QueueScreenState
  /** Visible server rows; hidden ids stay passed so the collapse can animate. */
  items: ReviewQueueItem[]
  hiddenIds: ReadonlySet<string>
  focusId: string | null
  left: number
  done: number
  tally: Tally
  filters: ReviewQueueFilters
  options: FilterOptions
  shownLine: string | null
  selecting: boolean
  picked: ReadonlySet<string>
  bulk: { label: string; disabled: boolean }
  bulkSkips: { label: string; reason: string }[] | null
  bulkError: string | null
  hasMore: boolean
  loadingMore: boolean
  /** The primary failure view and the raw query for the inline retry. */
  errorView: React.ReactNode
  query: QueryStateQuery<unknown>
  /** A later page failed while its rows are held: keep the list, offer the retry beside Load more. */
  moreFailed: boolean
  phone: boolean
  markHref: string
  searchRef: React.RefObject<HTMLInputElement | null>
  onOpen(id: string): void
  onPick(id: string): void
  onToggleSelect(): void
  onBulk(): void
  onDismissSkips(): void
  onFilters(f: ReviewQueueFilters): void
  onLoadMore(): void
}

export function QueueColumn(p: QueueColumnProps) {
  const set = (f: ReviewQueueFilters) => p.onFilters(f)
  const showChrome = p.state === "queue" || p.state === "sparse" || p.state === "no-match"
  const section = useRef<HTMLElement>(null)
  const moreButton = useRef<HTMLButtonElement>(null)
  // Paging ended on a render where the one Load more control still holds focus (it unmounts in this commit).
  // Read here because by the layout effect focus is already on <body>; the effect then puts it back, but only
  // if nothing else took it.
  const hadMoreFocus = !p.hasMore && !p.moreFailed && typeof document !== "undefined" && moreButton.current !== null && document.activeElement === moreButton.current
  useLayoutEffect(() => { focusAfterPagingEnds(document, section.current, hadMoreFocus) }, [hadMoreFocus])
  return (
    <section ref={section} tabIndex={-1} aria-label="Review queue" data-review-column className="grid min-h-0 min-w-0 content-start gap-3 bg-surface-container-low p-4 shell-sm:overflow-y-auto shell-sm:[scrollbar-width:thin] shell-sm:border-e shell-sm:border-outline-variant shell-sm:p-[18px] shell-lg:p-[22px] shell-lg:pe-4">
      {p.state === "loading" ? <QueueLoading /> : null}
      {p.state === "error" ? p.errorView : null}
      {p.state === "first-run" ? <FirstRun markHref={p.markHref} phone={p.phone} /> : null}
      {p.state === "nothing-waiting" ? <NothingWaiting /> : null}
      {p.state === "cleared" ? <Cleared tally={p.tally} markHref={p.markHref} /> : null}
      {showChrome ? (
        <>
          <QueueHeader left={p.left} done={p.done} />
          <div className="flex items-center gap-2">
            <button type="button" onClick={p.onToggleSelect} aria-pressed={p.selecting} className="rounded-[14px] bg-surface-container-lowest px-3.5 py-[9px] text-[13px] font-bold shadow-[inset_0_0_0_1.5px_var(--color-outline)] active:scale-[.97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11">
              {p.selecting ? "Cancel" : "Select"}
            </button>
            <span className="flex-1" />
            <button type="button" onClick={p.onBulk} disabled={p.bulk.disabled} className="rounded-[14px] bg-primary px-3.5 py-[9px] text-[13px] font-bold text-on-primary active:scale-[.97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:bg-surface-container-high disabled:text-on-surface-variant disabled:shadow-[inset_0_0_0_1.5px_var(--color-outline)] pointer-coarse:min-h-11">
              {p.bulk.label}
            </button>
          </div>
          {p.bulkError ? <div role="alert" className="text-[13px] text-error">Couldn't approve: {p.bulkError}</div> : null}
          {p.bulkSkips && p.bulkSkips.length > 0 ? (
            <div role="status" className="grid gap-1.5 rounded-[14px] bg-surface-container px-3.5 py-2.5 text-[13px]">
              <div className="flex items-center justify-between gap-3">
                <b>Some answers were skipped</b>
                <button type="button" onClick={p.onDismissSkips} className="text-primary focus-visible:outline-2 focus-visible:outline-primary pointer-coarse:min-h-11">Dismiss</button>
              </div>
              <ul className="m-0 list-disc ps-4 text-on-surface-variant">
                {p.bulkSkips.map((s) => (
                  <li key={s.label}>{s.label}: {s.reason}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <FilterBar
            filters={p.filters}
            options={p.options}
            shownLine={p.shownLine}
            searchRef={p.searchRef}
            onSearch={(q) => set({ ...p.filters, q })}
            onSort={(sort) => set({ ...p.filters, sort })}
            onToggle={(c, v) => set(toggleFilter(p.filters, c, v))}
            onRemove={(c, v) => set(removeFilter(p.filters, c, v))}
          />
          {p.state === "no-match" ? (
            <NoMatch onClear={() => set(clearFilters(p.filters))} />
          ) : (
            <ul className="m-0 grid list-none gap-1 p-0" aria-label="Answers to check">
              {p.items.map((item) => (
                <QueueRow key={item.itemId} item={item} focused={item.itemId === p.focusId} gone={p.hiddenIds.has(item.itemId)} selecting={p.selecting} picked={p.picked.has(item.itemId)} onOpen={p.onOpen} onPick={p.onPick} />
              ))}
            </ul>
          )}
          {p.state === "sparse" ? <SparseNote markHref={p.markHref} /> : null}
          <div role="status" aria-live="polite" className="text-center text-[13px] text-on-surface-variant">{p.loadingMore ? "Loading more answers…" : p.moreFailed ? "Couldn't load more answers." : ""}</div>
          {p.hasMore || p.moreFailed ? (
            <div className="flex justify-center">
              <button ref={moreButton} data-review-more type="button" onClick={() => { if (!p.loadingMore) { if (p.moreFailed) void p.query.refetch(); else p.onLoadMore() } }} aria-disabled={p.loadingMore} className="rounded-[14px] px-3.5 py-2 text-[13px] font-bold text-primary focus-visible:outline-2 focus-visible:outline-primary pointer-coarse:min-h-11">{p.loadingMore ? "Loading…" : p.moreFailed ? "Try again" : "Load more"}</button>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  )
}
