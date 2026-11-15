/*
 * Packet B2a · the decision table behind `useDialogHistory`.
 *
 * Opening a `Modal` or `NavDrawer` pushes one history entry so that browser
 * back closes the overlay instead of navigating the page underneath it away
 * — the dossier's history-trap finding (`nav-1`/`nav-3`/`nav-4`). A
 * dismissible overlay's popstate closes it and stops there; `ConfirmModal`
 * (`dismissible={false}`) re-pushes the entry instead, since a stray back
 * gesture must not silently answer a destructive confirmation on the
 * reader's behalf.
 *
 * Pure and stateless by design: `hasEntry` is the caller's own record of
 * whether it has already pushed (a ref in `useDialogHistory`, not something
 * this function can observe), so every call is a plain lookup with no
 * hidden state to desync from the DOM.
 */

export type DialogHistoryEvent = "open" | "close" | "popstate"

export function nextDialogHistoryAction(input: {
  event: DialogHistoryEvent
  dismissible: boolean
  hasEntry: boolean
}): "push" | "pop" | "repush" | "closeOnly" | "none" {
  const { event, hasEntry, dismissible } = input

  if (event === "open") {
    return hasEntry ? "none" : "push"
  }

  if (event === "close") {
    return hasEntry ? "pop" : "none"
  }

  // event === "popstate"
  if (!hasEntry) return "none"
  return dismissible ? "closeOnly" : "repush"
}

/**
 * Is `historyState` (a `window.history.state` value) still exactly the entry a
 * dialog pushed at index `idx`? Same react-router index AND `usr.lemelyDialog`
 * set. A replace keeps the index but drops the flag, so it fails the second
 * half; a push past the entry fails the first. With `id`, it must also be the
 * entry that push made: a later dialog pushed at the same index carries another
 * id, so a stale unwind cannot pop it.
 */
export function isDialogEntry(historyState: unknown, idx: number | null, id?: number | null): boolean {
  if (idx === null || typeof historyState !== "object" || historyState === null) return false
  const state = historyState as { idx?: unknown; usr?: unknown }
  if (state.idx !== idx) return false
  const usr = state.usr
  if (typeof usr !== "object" || usr === null) return false
  const flags = usr as { lemelyDialog?: unknown; lemelyDialogId?: unknown }
  if (flags.lemelyDialog !== true) return false
  return id === undefined || id === null || flags.lemelyDialogId === id
}
