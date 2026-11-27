import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryObserver } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"
import { reviewQueuePageOptions } from "@/lib/hooks/useTeacherApi"
import { EMPTY_FILTERS, filterKey } from "@/lib/reviewQueueQuery"
import type { ReviewQueueItem, ReviewQueueList } from "@/lib/teacherTypes"
import { QueueColumn, type QueueColumnProps } from "@/portals/teacher/screens/review/QueueColumn"
import { QueueLoadError } from "@/portals/teacher/screens/review/ReviewQueue"
import { isLoadingMore, pageableCursor, queueLoad, queueScreenState, reconcileCursor } from "@/portals/teacher/screens/review/reviewQueueModel"

/*
 * A failed "Load more" must not take the rows already on screen with it.
 *
 * The page past the first has its own query key. `placeholderData: previous`
 * shows the last page while it loads, but once that page fails the query has no
 * data of its own and react-query reports `status: "error"`, `data: undefined`.
 * The screen read that as a first-load failure and replaced the list and the
 * answer panel with the full-screen error, although `pages` still held the rows.
 *
 * ReviewQueue.tsx needs a browser to mount (vitest runs in node, no jsdom: see
 * vitest.config.ts), so this proves the wiring in three layers: a real
 * `QueryObserver` over the screen's own query options feeds the screen's own
 * `queueLoad` and `queueScreenState`; the real `QueueColumn` renders what those
 * decide; and the screen's source is pinned to that same call.
 */

const DIR = join(import.meta.dirname, "../../src/portals/teacher/screens/review")

function item(over: Partial<ReviewQueueItem>): ReviewQueueItem {
  return {
    itemId: "i1",
    source: "student_attempt",
    attemptId: "a1",
    paperId: null,
    questionResultId: "qr1",
    studentId: "s1",
    studentDisplayName: "Layla Hassan",
    classId: "c1",
    className: "10B",
    subjectCode: "0580",
    paperNumber: 4,
    paperVariant: 2,
    sessionMonth: "May/June",
    sessionYear: 2025,
    questionId: "4(b)",
    reason: "low_confidence",
    status: "open",
    createdAt: "2026-11-14T10:00:00Z",
    waitingHours: 3,
    aiAwardedMarks: 4,
    maximumMarks: 5,
    confidenceScore: 0.64,
    reviewReason: null,
    ...over,
  }
}

const PAGE1: ReviewQueueList = {
  items: [item({ itemId: "i1", studentDisplayName: "Layla Hassan" }), item({ itemId: "i2", studentDisplayName: "Omar Fathy" })],
  nextCursor: "c1",
  total: 5,
  subjectCodes: ["0580"],
  hasHistory: true,
}

const KEY = filterKey(EMPTY_FILTERS)
const OTHER = { ...EMPTY_FILTERS, q: "layla" }

const ok = (page: ReviewQueueList) => async () => page
const fails = async (): Promise<ReviewQueueList> => {
  throw new Error("network down")
}

/** The screen's own query options (key, placeholderData), with only the fetch swapped. */
function options(filters: typeof EMPTY_FILTERS, cursor: string | undefined, queryFn: () => Promise<ReviewQueueList>) {
  return { ...reviewQueuePageOptions(filters, cursor), queryFn }
}

function observer() {
  return new QueryObserver(new QueryClient({ defaultOptions: { queries: { retry: false } } }), options(EMPTY_FILTERS, undefined, ok(PAGE1)))
}

async function settled(o: ReturnType<typeof observer>, status: "success" | "error") {
  await vi.waitFor(() => expect(o.getCurrentResult().status).toBe(status))
  return o.getCurrentResult()
}

describe("failed Load more keeps the held rows (real QueryObserver + model)", () => {
  it("keeps recovery visible after every loaded answer is resolved", () => {
    expect(queueScreenState({ status: "success", visibleCount: 0, openTotal: 3, filtersActive: false, hasHistory: true, decidedThisSession: 2, moreFailed: true })).toBe("queue")
  })

  it("does not expose a previous filter page as pageable while the new first page loads", async () => {
    const o = observer()
    const stop = o.subscribe(() => {})
    await settled(o, "success")
    o.setOptions(options(OTHER, undefined, () => new Promise(() => {})))
    const pending = o.getCurrentResult()
    expect(pending.isPlaceholderData).toBe(true)
    const load = queueLoad(pending, { key: KEY, data: PAGE1 }, filterKey(OTHER), 0)
    expect(load.page).toBeUndefined()
    stop()
  })
  it("is not Cleared while the server still has answers to load, only when nothing remains", async () => {
    const o = observer()
    const stop = o.subscribe(() => {})
    const first = await settled(o, "success")
    stop()
    const load = queueLoad(first, { key: KEY, data: PAGE1 }, KEY, PAGE1.items.length)
    const base = { status: load.status, visibleCount: 0, openTotal: 3, filtersActive: false, hasHistory: true, decidedThisSession: 2 }
    // Every loaded row resolved; the page says there is a next cursor.
    expect(queueScreenState({ ...base, moreRemain: !!load.page?.nextCursor })).toBe("queue")
    // Same with a filter on: the way forward is Load more, not "no match".
    expect(queueScreenState({ ...base, filtersActive: true, moreRemain: !!load.page?.nextCursor })).toBe("queue")
    // Last page: nothing remains server-side, so Cleared.
    const last = { ...PAGE1, nextCursor: null, total: 2 }
    expect(queueScreenState({ ...base, openTotal: 0, moreRemain: !!last.nextCursor })).toBe("cleared")
    expect(queueScreenState({ ...base, openTotal: 0, filtersActive: true, moreRemain: false })).toBe("no-match")
  })

  it("pages only from real data of the current filter, never from a placeholder", async () => {
    const o = observer()
    const stop = o.subscribe(() => {})
    const first = await settled(o, "success")
    const key = filterKey(EMPTY_FILTERS)
    expect(pageableCursor(first, queueLoad(first, { key, data: PAGE1 }, key, 2).page)).toBe("c1")

    // Filter changes: the previous filter's page 1 stays on screen as placeholder, cursor and all.
    o.setOptions(options(OTHER, undefined, () => new Promise(() => {})))
    const pending = o.getCurrentResult()
    expect(pending.isPlaceholderData).toBe(true)
    expect(pending.data?.nextCursor).toBe("c1")
    // Even if a caller were handed that placeholder page, it is not pageable.
    expect(pageableCursor(pending, pending.data)).toBeUndefined()
    expect(pageableCursor(pending, queueLoad(pending, { key, data: PAGE1 }, filterKey(OTHER), 0).page)).toBeUndefined()
    stop()
  })

  it("does not page while this filter's next page is itself loading", async () => {
    const o = observer()
    const stop = o.subscribe(() => {})
    await settled(o, "success")
    o.setOptions(options(EMPTY_FILTERS, "c1", () => new Promise(() => {})))
    const loadingMore = o.getCurrentResult()
    expect(loadingMore.isPlaceholderData).toBe(true)
    expect(pageableCursor(loadingMore, PAGE1)).toBeUndefined()
    stop()
  })

  it("never lets a cursor outlive its filter, so coming back starts at the first page", async () => {
    const A = filterKey(EMPTY_FILTERS)
    const B = filterKey(OTHER)
    const onA = reconcileCursor({ key: A, cursor: "c1" }, A)
    expect(onA).toEqual({ key: A, cursor: "c1" })
    // Away to B: the cursor is dropped on the same render, not by a later effect.
    const onB = reconcileCursor(onA, B)
    expect(onB).toBeNull()
    // Back to A: nothing remembers "c1", so the query is page 1 again.
    const backOnA = reconcileCursor(onB, A)
    expect(backOnA).toBeNull()
    const cursor = backOnA?.cursor
    expect(options(EMPTY_FILTERS, cursor, ok(PAGE1)).queryKey).toEqual(reviewQueuePageOptions(EMPTY_FILTERS, undefined).queryKey)
    expect(reconcileCursor(null, A)).toBeNull()
  })

  it("reads as an error with no data of its own, which is what hid the list", async () => {
    const o = observer()
    const stop = o.subscribe(() => {})
    await settled(o, "success")
    o.setOptions(options(EMPTY_FILTERS, "c1", fails))
    const failed = await settled(o, "error")
    expect(failed.data).toBeUndefined()
    stop()
  })

  it("keeps the queue state, the held page and a retry when the next page fails", async () => {
    const o = observer()
    const stop = o.subscribe(() => {})
    await settled(o, "success")
    o.setOptions(options(EMPTY_FILTERS, "c1", fails))
    const failed = await settled(o, "error")
    stop()

    const held = { key: KEY, data: PAGE1 }
    const load = queueLoad(failed, held, KEY, PAGE1.items.length)
    expect(load.moreFailed).toBe(true)
    expect(load.status).toBe("success")
    expect(load.page?.nextCursor).toBe("c1")
    expect(load.page?.total).toBe(5)
    expect(
      queueScreenState({
        status: load.status,
        visibleCount: PAGE1.items.length,
        openTotal: load.page?.total ?? 0,
        filtersActive: false,
        hasHistory: load.page?.hasHistory ?? true,
        decidedThisSession: 0,
      }),
    ).toBe("queue")
  })

  it("still shows the full-screen error when the first load fails", async () => {
    const o = new QueryObserver(new QueryClient({ defaultOptions: { queries: { retry: false } } }), options(EMPTY_FILTERS, undefined, fails))
    const stop = o.subscribe(() => {})
    const failed = await settled(o, "error")
    stop()

    const load = queueLoad(failed, null, KEY, 0)
    expect(load.moreFailed).toBe(false)
    expect(load.status).toBe("error")
    expect(load.page).toBeUndefined()
    expect(queueScreenState({ status: load.status, visibleCount: 0, openTotal: 0, filtersActive: false, hasHistory: true, decidedThisSession: 0 })).toBe("error")
  })

  it("still shows the full-screen error when a changed filter's first page fails", async () => {
    const o = observer()
    const stop = o.subscribe(() => {})
    await settled(o, "success")
    o.setOptions(options(OTHER, undefined, fails))
    const failed = await settled(o, "error")
    stop()

    // Rows and the held page belong to the previous filter, so nothing is held for this key.
    const load = queueLoad(failed, { key: KEY, data: PAGE1 }, filterKey(OTHER), 0)
    expect(load.moreFailed).toBe(false)
    expect(load.status).toBe("error")
    expect(load.page).toBeUndefined()
  })

  it("stays Cleared through a background refetch of the last page, with nothing left to load", async () => {
    const LAST: ReviewQueueList = { ...PAGE1, nextCursor: null, total: 4 }
    const o = new QueryObserver(new QueryClient({ defaultOptions: { queries: { retry: false } } }), options(EMPTY_FILTERS, "c1", ok(LAST)))
    const stop = o.subscribe(() => {})
    await settled(o, "success")
    // What invalidateAfterResolve does five seconds after each resolve: refetch the page on screen.
    o.setOptions(options(EMPTY_FILTERS, "c1", () => new Promise(() => {})))
    void o.refetch()
    const refetching = o.getCurrentResult()
    expect(refetching.isFetching).toBe(true)
    expect(refetching.isPlaceholderData).toBe(false)
    stop()

    const load = queueLoad(refetching, { key: KEY, data: LAST }, KEY, LAST.items.length)
    expect(load.moreFailed).toBe(false)
    const state = queueScreenState({ status: load.status, visibleCount: 0, openTotal: 0, filtersActive: false, hasHistory: true, decidedThisSession: 4, moreRemain: !!load.page?.nextCursor, moreFailed: load.moreFailed })
    expect(state).toBe("cleared")
    // The screen hands the state exactly the model's flag, with no extra "fetching" clause of its own.
    expect(readFileSync(join(DIR, "ReviewQueue.tsx"), "utf8")).toMatch(/moreFailed: load\.moreFailed,\n/)
  })

  it("says Loading only for a real Load more or its retry, never for a background refetch", async () => {
    const LAST: ReviewQueueList = { ...PAGE1, nextCursor: null, total: 4 }
    const o = observer()
    const stop = o.subscribe(() => {})
    await settled(o, "success")

    // Real Load more: the next page loads while the held one shows as placeholder.
    o.setOptions(options(EMPTY_FILTERS, "c1", () => new Promise(() => {})))
    const more = o.getCurrentResult()
    expect(more.isFetching && more.isPlaceholderData).toBe(true)
    expect(isLoadingMore(more, "c1")).toBe(true)

    stop()

    // Page 2 is on screen, then a resolve schedules a background refetch of it.
    const b = new QueryObserver(new QueryClient({ defaultOptions: { queries: { retry: false } } }), options(EMPTY_FILTERS, "c1", ok(LAST)))
    const stopB = b.subscribe(() => {})
    await settled(b, "success")
    b.setOptions(options(EMPTY_FILTERS, "c1", () => new Promise(() => {})))
    void b.refetch()
    const background = b.getCurrentResult()
    expect(background.isFetching).toBe(true)
    expect(isLoadingMore(background, "c1")).toBe(false)
    // No cursor means the first page: that is never Load more either.
    expect(isLoadingMore({ isFetching: true, isPlaceholderData: true }, undefined)).toBe(false)
    stopB()

    // Retry after a failed Load more is a Load more again.
    const r = observer()
    const stopR = r.subscribe(() => {})
    await settled(r, "success")
    r.setOptions(options(EMPTY_FILTERS, "c1", fails))
    await settled(r, "error")
    r.setOptions(options(EMPTY_FILTERS, "c1", () => new Promise(() => {})))
    void r.refetch()
    const retrying = r.getCurrentResult()
    expect(retrying.isFetching && retrying.isPlaceholderData).toBe(true)
    expect(isLoadingMore(retrying, "c1")).toBe(true)
    // And while the failed state itself is still being refetched.
    expect(isLoadingMore({ isFetching: true, isError: true }, "c1")).toBe(true)
    stopR()
  })
})

function columnProps(over: Partial<QueueColumnProps>): QueueColumnProps {
  return {
    state: "queue",
    items: PAGE1.items,
    hiddenIds: new Set(),
    focusId: "i1",
    left: 5,
    done: 0,
    tally: { decided: 0, changed: 0, dismissed: 0 },
    filters: EMPTY_FILTERS,
    options: { classes: [], subjects: [], subjectName: (c) => c },
    shownLine: null,
    selecting: false,
    picked: new Set(),
    bulk: { label: "No clear answers", disabled: true },
    bulkSkips: null,
    bulkError: null,
    hasMore: true,
    loadingMore: false,
    errorView: createElement(QueueLoadError, { query: FAILED }),
    query: { status: "success", data: PAGE1, error: null, refetch: () => {} },
    moreFailed: false,
    phone: false,
    markHref: "/teacher/grading",
    searchRef: { current: null },
    onOpen: () => {},
    onPick: () => {},
    onToggleSelect: () => {},
    onBulk: () => {},
    onDismissSkips: () => {},
    onFilters: () => {},
    onLoadMore: () => {},
    ...over,
  }
}

function render(props: QueueColumnProps): string {
  return renderToStaticMarkup(createElement(MemoryRouter, null, createElement(QueueColumn, props)))
}

const FAILED = { status: "error", data: undefined, error: new Error("network down"), refetch: () => {} } as const

describe("QueueColumn renders the failure where it happened (real component)", () => {
  it("keeps every held row and puts the retry in the Load more slot", () => {
    const html = render(columnProps({ query: FAILED, moreFailed: true }))
    expect(html).toContain("Layla Hassan")
    expect(html).toContain("Omar Fathy")
    expect(html).toContain("Couldn&#x27;t load more answers.")
    expect(html).toContain("Try again")
    expect(html).not.toContain("Load more")
    // The list is still the page; no second page heading appears for the inline failure.
    expect([...html.matchAll(/<h1\b/g)]).toHaveLength(1)
  })

  it("keeps the ordinary Load more button when nothing failed", () => {
    const html = render(columnProps({}))
    expect(html).toContain("Load more")
    expect(html).not.toContain("Try again")
  })

  it("keeps the retry on screen when every loaded answer has been resolved", () => {
    // The screen's own decision for "nothing visible, three unloaded, the later page failed".
    const state = queueScreenState({ status: "success", visibleCount: 0, openTotal: 3, filtersActive: false, hasHistory: true, decidedThisSession: 2, moreFailed: true })
    expect(state).toBe("queue")
    const html = render(columnProps({ state, query: FAILED, moreFailed: true, hiddenIds: new Set(PAGE1.items.map((i) => i.itemId)) }))
    expect(html).toContain("Try again")
    expect(html).toContain("Couldn&#x27;t load more answers.")
    expect(html).toContain("data-gone")
  })

  it("offers Load more beside an empty list when every loaded answer is resolved but more remain", () => {
    const state = queueScreenState({ status: "success", visibleCount: 0, openTotal: 3, filtersActive: false, hasHistory: true, decidedThisSession: 2, moreRemain: true })
    const html = render(columnProps({ state, hasMore: true, hiddenIds: new Set(PAGE1.items.map((i) => i.itemId)) }))
    expect(html).toContain("Load more")
    expect(html).toContain("data-review-more")
  })

  const control = (html: string) => [...html.matchAll(/<button\b[^>]*data-review-more[^>]*>([^<]*)<\/button>/g)]
  const region = (html: string) => [...html.matchAll(/<div\b[^>]*role="status"[^>]*aria-live="polite"[^>]*>([^<]*)<\/div>/g)]

  it("is one control in one slot whether it says Load more, Loading or Try again", () => {
    const labels = [
      [columnProps({}), "Load more"],
      [columnProps({ loadingMore: true }), "Loading…"],
      [columnProps({ query: FAILED, moreFailed: true }), "Try again"],
    ] as const
    for (const [props, label] of labels) {
      const found = control(render(props))
      expect(found).toHaveLength(1)
      expect(found[0][1]).toBe(label)
    }
    // Loading keeps it focusable (aria-disabled, never `disabled`) so focus is not dropped mid-load.
    const loading = control(render(columnProps({ loadingMore: true })))[0][0]
    expect(loading).toContain('aria-disabled="true"')
    expect(loading).not.toMatch(/\sdisabled(=|\s|>)/)
  })

  it("mounts the live region before anything is announced and keeps it through every state", () => {
    const states = [
      [columnProps({}), ""],
      [columnProps({ loadingMore: true }), "Loading more answers…"],
      [columnProps({ query: FAILED, moreFailed: true }), "Couldn&#x27;t load more answers."],
      [columnProps({ hasMore: false }), ""],
    ] as const
    for (const [props, said] of states) {
      const found = region(render(props))
      expect(found).toHaveLength(1)
      expect(found[0][1]).toBe(said)
    }
    // With no more pages the control is gone but the region is still there to announce into.
    expect(control(render(columnProps({ hasMore: false })))).toHaveLength(0)
  })

  it("replaces the list with the one full-screen error, headed once, when the first load failed", () => {
    const html = render(columnProps({ state: "error", items: [], query: FAILED }))
    expect(html).not.toContain("Layla Hassan")
    expect(html).toContain("Couldn&#x27;t load the review queue.")
    expect(html).toContain("Try again")
    expect([...html.matchAll(/<h1\b[^>]*>([^<]*)<\/h1>/g)].map((m) => m[1])).toEqual(["Review"])
  })
})

describe("ReviewQueue.tsx is wired to that decision", () => {
  const screen = readFileSync(join(DIR, "ReviewQueue.tsx"), "utf8")

  it("derives status, page and the retry flag from the held rows and page of this filter", () => {
    expect(screen).toMatch(/queueLoad\(queue, held, key, rows\.length\)/)
    expect(screen).toMatch(/setHeld\(\{ key, data: queue\.data \}\)/)
    expect(screen).toMatch(/moreFailed=\{load\.moreFailed\}/)
    expect(screen).toMatch(/query=\{queueQuery\}/)
    expect(screen).toMatch(/refetch: \(\) => queue\.refetch\(\)/)
  })

  it("reads total, cursor, subjects and history from the held page, not the failed query", () => {
    expect(screen).not.toMatch(/queue\.data\?\.(total|nextCursor|subjectCodes|hasHistory)/)
    expect(screen).toMatch(/hasMore=\{!!load\.page\?\.nextCursor\}/)
  })

  it("tells the screen state when the server still has more, from the page and not the loaded rows", () => {
    expect(screen).toMatch(/moreRemain: !!load\.page\?\.nextCursor/)
  })

  it("keys the cursor to the filter on the same render and pages only from real current-filter data", () => {
    // Derived, never held over: a cursor for another filter reads as none, and is dropped in the same render.
    expect(screen).toMatch(/const live = reconcileCursor\(cursorState, key\)/)
    expect(screen).toMatch(/if \(live !== cursorState\) setCursorState\(live\)/)
    expect(screen).toMatch(/const cursor = live\?\.cursor/)
    // No effect resets it: that is the window the placeholder page used to slip through.
    expect(screen).not.toMatch(/useEffect\(\(\) => \{[^}]*setCursorState/)
    expect(screen).toMatch(/const next = pageableCursor\(queue, load\.page\)/)
    expect(screen).toMatch(/if \(next\) setCursorState\(\{ key, cursor: next \}\)/)
  })

  it("hands the column one control and one region, and a place for focus to go when paging ends", () => {
    const column = readFileSync(join(DIR, "QueueColumn.tsx"), "utf8")
    expect([...column.matchAll(/ref=\{moreButton\}/g)]).toHaveLength(1)
    expect(column).toMatch(/data-review-more[^]*?>\{p\.loadingMore \? "Loading…" : p\.moreFailed \? "Try again" : "Load more"\}<\/button>/)
    expect(column).toMatch(/focusAfterPagingEnds\(document, section\.current, hadMoreFocus\)/)
  })

  it("derives Loading from the model and offsets the toast by the layout width, not the scrollbar-inclusive one", () => {
    expect(screen).toMatch(/loadingMore=\{isLoadingMore\(queue, cursor\)\}/)
    const undo = readFileSync(join(DIR, "UndoBar.tsx"), "utf8")
    expect(undo).toMatch(/document\.documentElement\.clientWidth - r\.right/)
    expect(undo).not.toMatch(/window\.innerWidth/)
  })

  it("gates the answer panel on the screen state, never on the raw query failure", () => {
    expect(screen).not.toMatch(/queue\.isError/)
    expect(screen).toMatch(/state !== "loading" && state !== "error"/)
  })

  it("leaves the page heading to QueryState's srHeading", () => {
    const states = readFileSync(join(DIR, "QueueStates.tsx"), "utf8")
    expect(screen).not.toMatch(/<h1 className="sr-only">/)
    expect(states).not.toMatch(/export function QueueError\b/)
    expect(screen).toMatch(/srHeading="Review"/)
    expect(screen).toMatch(/errorView=\{<QueueLoadError query=\{queueQuery\} \/>\}/)
  })
})
