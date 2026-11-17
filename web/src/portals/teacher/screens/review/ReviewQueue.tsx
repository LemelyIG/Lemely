import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { invalidateAfterResolve, useBulkApproveReview, useReviewItem, useReviewQueuePage, useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { subjectNameFor } from "@/lib/reference"
import { filterKey, filtersActive, filtersFromSearch, filtersToSearch, type ReviewQueueFilters } from "@/lib/reviewQueueQuery"
import { postReviewDecision, type ReviewDecision } from "@/lib/reviewApi"
import { teacherLoadFailureMessage, teacherMutationFailureMessage } from "@/lib/teacherOutcome"
import type { ReviewQueueItem } from "@/lib/teacherTypes"
import { useNativeFrame } from "@/lib/useNativeFrame"
import { AnswerPage } from "./AnswerPage"
import { AnswerPanel } from "./AnswerPanel"
import { answerViewFromReviewItem } from "./answerView"
import { initialMarkState, resolveBody, totalOf, type MarkState } from "./markModel"
import { QueueColumn } from "./QueueColumn"
import { Cleared } from "./QueueStates"
import { UndoBar } from "./UndoBar"
import { mergeReviewPages } from "./reviewLabels"
import { SKIP_LINE, bulkButton, isClearItem, nextFocusAfter, positionOf, queueScreenState, questionLabel, shownLine } from "./reviewQueueModel"
import { useAnswerImages } from "./useAnswerImages"
import { usePendingDecisions } from "./usePendingDecisions"
import "./review.css"

/** Where "Mark papers" and "Mark another class set" go until L6/L8 settle the class-set upload route. */
const MARK_HREF = "/teacher/grading"

const BTN = "rounded-[14px] px-[18px] py-[11px] text-[14px] font-bold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"

/** The teacher review queue: the element for both `review` and `review/:itemId`. */
export function ReviewQueue() {
  const { itemId } = useParams<{ itemId?: string }>()
  const [sp, setSp] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { phone } = useNativeFrame()
  const filters = useMemo(() => filtersFromSearch(sp), [sp])
  const key = filterKey(filters)
  const qs = filtersToSearch(filters).toString()
  const suffix = qs ? `?${qs}` : ""

  const [selecting, setSelecting] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [skips, setSkips] = useState<{ label: string; reason: string }[] | null>(null)

  // Load more, merged and deduped; reset on any filter change.
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [pages, setPages] = useState<{ key: string; items: ReviewQueueItem[] }>({ key: "", items: [] })
  const [merged, setMerged] = useState<unknown>(undefined)
  const queue = useReviewQueuePage(filters, cursor)
  if (queue.data && queue.data !== merged) {
    setMerged(queue.data)
    setPages((prev) => mergeReviewPages(prev, { key, items: queue.data!.items }))
  }
  useEffect(() => { setCursor(undefined) }, [key])

  const classes = useTeacherClasses()
  const reference = useReference()
  const options = useMemo(() => ({
    classes: (classes.data?.classes ?? []).map((c) => ({ id: c.id, label: c.label })),
    subjects: queue.data?.subjectCodes ?? [],
    subjectName: (code: string) => subjectNameFor(reference.data, code),
  }), [classes.data, queue.data?.subjectCodes, reference.data])

  // Owns the deferred commit: its pagehide and unmount flush (keepalive) live in the hook.
  const decisions = usePendingDecisions(
    (d, o) => postReviewDecision(d, o),
    (d, row) => {
      if (d.kind === "resolve") invalidateAfterResolve(queryClient, row as ReviewQueueItem)
      else queryClient.invalidateQueries({ queryKey: ["teacher", "review"] })
    },
  )
  const hidden = useMemo(() => new Set(decisions.state.hidden), [decisions.state.hidden])
  const rows = pages.key === key ? pages.items : []
  const open = rows.filter((r) => !hidden.has(r.itemId))
  const openIds = open.map((r) => r.itemId)
  const total = Math.max(0, (queue.data?.total ?? 0) - rows.filter((r) => hidden.has(r.itemId)).length)

  const state = queueScreenState({
    status: queue.isPending && !queue.data ? "pending" : queue.isError && !queue.data ? "error" : "success",
    visibleCount: open.length,
    openTotal: total,
    filtersActive: filtersActive(filters),
    hasHistory: queue.data?.hasHistory ?? true,
    decidedThisSession: decisions.state.tally.decided,
  })

  // Focus: the URL item, else (desktop) the first open row.
  const focusId = itemId ?? (phone ? null : (openIds[0] ?? null))
  const detail = useReviewItem(focusId ?? undefined)
  const view = detail.data ? answerViewFromReviewItem(detail.data) : null
  const images = useAnswerImages(focusId ?? undefined, view?.hasScan ?? false)
  const [mark, setMark] = useState<{ id: string; state: MarkState; note: string } | null>(null)
  const markState = view && mark?.id === view.key ? mark.state : view ? initialMarkState(view.points, view.lemelyMarks, view.maximumMarks) : null
  const note = view && mark?.id === view.key ? mark.note : ""

  const go = useCallback((id: string | null, opts: { replace?: boolean } = {}) => {
    navigate(id ? `/teacher/review/${id}${suffix}` : `/teacher/review${suffix}`, { replace: opts.replace ?? !phone })
  }, [navigate, suffix, phone])

  const setFilters = useCallback((f: ReviewQueueFilters) => {
    setSelecting(false)
    setPicked(new Set())
    setSp(filtersToSearch(f), { replace: true })
  }, [setSp])

  const bulk = useBulkApproveReview()
  const clearIds = open.filter(isClearItem).map((r) => r.itemId)

  function decideFocused(noteOverride?: string) {
    if (!view || !markState || !detail.data || view.status !== "open") return
    const text = noteOverride ?? note
    const d: ReviewDecision = view.integrity
      ? { kind: "dismiss", itemId: view.key, label: questionLabel(detail.data), body: { note: text.trim() || undefined } }
      : {
          kind: "resolve",
          itemId: view.key,
          label: questionLabel(detail.data),
          changed: totalOf(view.points, markState, view.maximumMarks) !== view.lemelyMarks,
          body: resolveBody({ points: view.points, state: markState, max: view.maximumMarks, lemely: view.lemelyMarks, note: text, canAdjust: view.canAdjust }),
        }
    const next = nextFocusAfter(openIds, view.key)
    decisions.decide(d)
    setMark(null)
    // Phone returns to the list (plan decision 14). Replace, so Back never reopens a decided answer.
    if (phone) go(null, { replace: true })
    else go(next, { replace: true })
  }

  function runBulk() {
    decisions.flush()
    const ids = selecting ? [...picked] : clearIds
    const snapshot = rows
    bulk.mutate(ids, {
      onSuccess: (res) => {
        decisions.bulkApproved(res.approved, res.skipped.length)
        setSkips(res.skipped.length ? res.skipped.map((s) => {
          const r = snapshot.find((x) => x.itemId === s.itemId)
          return { label: r ? `${r.studentDisplayName} · ${questionLabel(r)}` : s.itemId, reason: SKIP_LINE[s.reason] ?? s.reason }
        }) : null)
        setSelecting(false)
        setPicked(new Set())
        if (focusId && res.approved.includes(focusId)) go(null, { replace: true })
      },
    })
  }

  // Keep the focused row visible as J/K/N move through the list.
  useEffect(() => {
    if (!focusId) return
    document.querySelector(`[data-review-row="${CSS.escape(focusId)}"]`)?.scrollIntoView({ block: "nearest" })
  }, [focusId])

  // Keyboard. No dependency list on purpose: it re-binds each render so the closure is never stale.
  const searchRef = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null
      if (t && (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.isContentEditable)) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); return }
      if (e.key === "Escape" && phone && itemId) { e.preventDefault(); go(null, { replace: false }); return }
      const at = focusId ? openIds.indexOf(focusId) : -1
      if (e.key === "j" || e.key === "n" || e.key === "N") { const n = openIds[at + 1]; if (n) { e.preventDefault(); go(n) } }
      if (e.key === "k") { const p = openIds[at - 1]; if (p) { e.preventDefault(); go(p) } }
      if ((e.key === "a" || e.key === "A") && view && !view.integrity && view.status === "open") { e.preventDefault(); decideFocused() }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  const pos = positionOf(openIds, focusId)
  const panelProps = view && markState ? {
    view,
    images,
    nav: { pos: pos.pos, total: pos.total, onPrev: () => go(openIds[pos.pos - 2] ?? null), onNext: () => go(openIds[pos.pos] ?? null) },
    marking: view.status === "open" ? {
      state: markState,
      onChange: (s: MarkState) => setMark({ id: view.key, state: s, note }),
      note,
      onNote: (n: string) => setMark({ id: view.key, state: markState, note: n }),
      onAccept: () => decideFocused(),
      onDismiss: (n: string) => decideFocused(n),
    } : null,
    showShortcuts: true,
  } : null

  const detailError = detail.isError ? (
    <div role="alert" className="grid justify-items-start gap-2.5 py-7">
      <h2 className="text-[24px] font-extrabold tracking-[-0.02em]">Couldn't load this answer.</h2>
      <p className="text-on-surface-variant">{teacherLoadFailureMessage(detail.error)}</p>
      <div className="flex gap-2">
        <button type="button" onClick={() => void detail.refetch()} className={`${BTN} bg-primary text-on-primary`}>Try again</button>
        <button type="button" onClick={() => go(null, { replace: false })} className={`${BTN} bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline)]`}>Back to queue</button>
      </div>
    </div>
  ) : null

  // Phone answer page.
  if (phone && itemId) {
    return (
      <>
        {detailError ?? (panelProps ? <AnswerPage {...panelProps} onBack={() => go(null, { replace: false })} /> : <div className="lm-rq-skel m-4 h-[60vh] rounded-[18px] bg-surface-container-high" role="status" aria-label="Loading the answer" />)}
        <UndoBar notice={decisions.state.notice} onUndo={decisions.undo} onClose={decisions.clearNotice} />
      </>
    )
  }

  const cleared = state === "cleared"
  const column = (
    <QueueColumn
      state={state}
      items={rows}
      hiddenIds={hidden}
      focusId={focusId}
      left={total}
      done={decisions.state.tally.decided}
      tally={decisions.state.tally}
      filters={filters}
      options={options}
      shownLine={filtersActive(filters) && total > 0 ? shownLine(open.length, total) : null}
      selecting={selecting}
      picked={picked}
      bulk={bulkButton({ selecting, picked: picked.size, clearCount: clearIds.length, pending: bulk.isPending })}
      bulkSkips={skips}
      bulkError={bulk.isError ? teacherMutationFailureMessage(bulk.error) : null}
      hasMore={!!queue.data?.nextCursor}
      loadingMore={queue.isFetching && !!cursor}
      errorMessage={queue.error ? teacherLoadFailureMessage(queue.error) : "Check your connection and try again."}
      phone={phone}
      markHref={MARK_HREF}
      searchRef={searchRef}
      onOpen={(id) => go(id, { replace: !phone })}
      onPick={(id) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })}
      onToggleSelect={() => { setSelecting((s) => !s); setPicked(new Set()) }}
      onBulk={runBulk}
      onDismissSkips={() => setSkips(null)}
      onFilters={setFilters}
      onLoadMore={() => setCursor(queue.data?.nextCursor ?? undefined)}
      onRetry={() => void queue.refetch()}
    />
  )

  return (
    <div className="-mx-3.5 grid min-h-[calc(100dvh-56px)] min-w-0 grid-cols-1 shell-sm:grid-cols-[minmax(300px,360px)_minmax(0,1fr)] shell-lg:-mx-[72px] shell-lg:grid-cols-[minmax(340px,400px)_minmax(0,1fr)]">
      {cleared ? (
        <div className="col-span-full grid place-items-center"><Cleared tally={decisions.state.tally} markHref={MARK_HREF} /></div>
      ) : (
        <>
          {column}
          {phone ? null : (
            <div className="sticky top-0 grid max-h-[100dvh] content-start self-start overflow-auto px-6 py-5 [scrollbar-width:thin] shell-lg:px-9 shell-lg:py-6">
              {state === "loading" ? <div className="lm-rq-skel h-[min(420px,60vh)] rounded-[18px] bg-surface-container-high" role="status" aria-label="Loading the answer" /> : null}
              {state !== "loading" && state !== "error" ? (detailError ?? (panelProps ? <AnswerPanel {...panelProps} /> : null)) : null}
            </div>
          )}
        </>
      )}
      <UndoBar notice={decisions.state.notice} onUndo={decisions.undo} onClose={decisions.clearNotice} />
    </div>
  )
}
