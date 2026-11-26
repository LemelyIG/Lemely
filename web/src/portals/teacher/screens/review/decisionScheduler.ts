import type { ReviewDecision } from "@/lib/reviewApi"
import { UNDO_WINDOW_MS } from "./pendingDecisions"

export interface SchedulerDeps {
  /** Sends one decision. `keepalive` is true when the page is going away. */
  fire: (d: ReviewDecision, keepalive: boolean) => void
  setTimeout: (fn: () => void, ms: number) => unknown
  clearTimeout: (handle: unknown) => void
}

/**
 * The undo hold, free of React and the DOM so it can be unit-tested with
 * injected timers. At most one decision is pending: deciding again sends the
 * previous one at once; `undo` cancels the send; `flush` sends now.
 */
export function createDecisionScheduler(deps: SchedulerDeps) {
  let pending: ReviewDecision | null = null
  let handle: unknown = null

  function cancelTimer() {
    if (handle !== null) deps.clearTimeout(handle)
    handle = null
  }

  function flush(keepalive = false) {
    cancelTimer()
    const d = pending
    pending = null
    if (d) deps.fire(d, keepalive)
  }

  return {
    decide(d: ReviewDecision) {
      flush()
      pending = d
      handle = deps.setTimeout(() => flush(), UNDO_WINDOW_MS)
    },
    /** True when a pending decision was cancelled. */
    undo(): boolean {
      if (!pending) return false
      cancelTimer()
      pending = null
      return true
    },
    flush,
  }
}
