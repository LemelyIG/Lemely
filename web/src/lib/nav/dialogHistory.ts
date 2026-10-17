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
