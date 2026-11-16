import { useCallback, useEffect, useReducer, useRef } from "react"
import { ApiError } from "@/lib/api"
import type { ReviewDecision } from "@/lib/reviewApi"
import { teacherMutationFailureMessage } from "@/lib/teacherOutcome"
import { createDecisionScheduler } from "./decisionScheduler"
import { BULK_TOAST_MS, INITIAL_DECISIONS, UNDO_WINDOW_MS, decisionsReducer } from "./pendingDecisions"

type Commit = (d: ReviewDecision, opts: { keepalive: boolean }) => Promise<unknown>

/**
 * Deferred commit for the queue's collapse-and-undo (approved mock, the review
 * queue's "row collapses with undo"). The backend has no reopen, so a decision
 * waits UNDO_WINDOW_MS before it is sent. Only one decision is undoable at a
 * time: deciding again commits the previous one at once. Leaving the page
 * (`pagehide`) or unmounting flushes with `keepalive`, so nothing is lost.
 * `commit` and `onCommitted` are read through refs, so callers need not memoise them.
 */
export function usePendingDecisions(commit: Commit, onCommitted: (d: ReviewDecision, row: unknown) => void) {
  const [state, dispatch] = useReducer(decisionsReducer, INITIAL_DECISIONS)
  const commitRef = useRef(commit)
  const committedRef = useRef(onCommitted)
  commitRef.current = commit
  committedRef.current = onCommitted
  const noticeTimer = useRef<number | null>(null)

  const fire = useCallback((d: ReviewDecision, keepalive: boolean) => {
    dispatch({ type: "commit-start", decision: d })
    commitRef
      .current(d, { keepalive })
      .then((row) => {
        dispatch({ type: "commit-ok", decision: d })
        committedRef.current(d, row)
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 409) dispatch({ type: "commit-conflict", decision: d })
        else dispatch({ type: "commit-failed", decision: d, message: teacherMutationFailureMessage(err) })
      })
  }, [])

  const scheduler = useRef<ReturnType<typeof createDecisionScheduler> | null>(null)
  if (scheduler.current === null) {
    scheduler.current = createDecisionScheduler({
      fire,
      setTimeout: (fn, ms) => window.setTimeout(fn, ms),
      clearTimeout: (h) => window.clearTimeout(h as number),
    })
  }
  const flush = useCallback((keepalive = false) => scheduler.current?.flush(keepalive), [])

  const hideNoticeAfter = useCallback((ms: number) => {
    if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current)
    noticeTimer.current = window.setTimeout(() => dispatch({ type: "clear-notice" }), ms)
  }, [])

  const decide = useCallback(
    (d: ReviewDecision) => {
      scheduler.current?.decide(d)
      dispatch({ type: "decide", decision: d })
      hideNoticeAfter(UNDO_WINDOW_MS)
    },
    [hideNoticeAfter],
  )

  const undo = useCallback(() => {
    if (scheduler.current?.undo()) dispatch({ type: "undo" })
  }, [])

  const bulkApproved = useCallback(
    (approved: string[], skipped: number) => {
      dispatch({ type: "bulk-ok", approved, skipped })
      hideNoticeAfter(BULK_TOAST_MS)
    },
    [hideNoticeAfter],
  )

  const clearNotice = useCallback(() => dispatch({ type: "clear-notice" }), [])

  useEffect(() => {
    const onHide = () => flush(true)
    window.addEventListener("pagehide", onHide)
    return () => {
      window.removeEventListener("pagehide", onHide)
      flush(true)
      if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current)
    }
  }, [flush])

  return { state, decide, undo, flush, bulkApproved, clearNotice }
}
