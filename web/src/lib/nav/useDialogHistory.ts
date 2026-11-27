import { useEffect, useRef } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { isDialogEntry, nextDialogHistoryAction } from "@/lib/nav/dialogHistory"
import { historyIndexOf } from "@/lib/nav/backgroundLocation"
import { dialogHistoryStack } from "@/lib/nav/dialogHistoryStack"

/*
 * Packet B2a · wires `nextDialogHistoryAction`'s decision table into an
 * actual history entry for `Modal` and `NavDrawer`.
 *
 * Opening pushes one entry (`state.lemelyDialog: true`, URL unchanged) so
 * browser back closes the overlay instead of navigating the page underneath
 * it away. Programmatic close (`onClose`/scrim/Escape/footer action) unwinds
 * that same entry with `navigate(-1)`. A `ConfirmModal` (`dismissible={false}`)
 * re-pushes on a browser-back popstate instead of closing, so a stray back
 * gesture cannot silently answer a destructive confirmation.
 *
 * Which overlay a given back press belongs to — and whether a popstate is
 * merely our own `navigate(-1)` arriving back — is decided by
 * `dialogHistoryStack`, module-level and shared, because `popstate` is a
 * window event that every mounted instance hears. See that file for why
 * neither decision can live in a per-instance ref.
 *
 * One case the plain push/pop pairing gets wrong on its own: a link inside the
 * overlay navigates. Links inside overlays REPLACE the dialog's entry
 * (`useDialogExitNavigate`), so the history reads [origin, destination] and
 * one Back returns to the origin. For anything that still navigates past the
 * entry, `unwindEntry` only calls `navigate(-1)` while the live history entry
 * is exactly the one this hook pushed (same index, `usr.lemelyDialog` set).
 */

let listening = false

/** Each push gets its own id, carried in the entry's state, so an unwind can tell its entry from a later one at the same index. */
let nextDialogId = 1

function onWindowPopState() {
  dialogHistoryStack.handlePopState(historyIndexOf(window.history.state))
  // The last overlay may have gone while its own move was in flight; now that move has landed, let go.
  stopListeningIfIdle()
}

function startListening() {
  if (listening) return
  window.addEventListener("popstate", onWindowPopState)
  listening = true
}

function stopListeningIfIdle() {
  if (!listening || dialogHistoryStack.size > 0 || dialogHistoryStack.hasPendingWork()) return
  window.removeEventListener("popstate", onWindowPopState)
  listening = false
}

export function useDialogHistory({
  open,
  dismissible,
  onClose,
}: {
  open: boolean
  dismissible: boolean
  onClose: () => void
}): void {
  const navigate = useNavigate()
  const location = useLocation()
  const hasEntryRef = useRef(false)
  const pushedIdxRef = useRef<number | null>(null)
  const pushedIdRef = useRef<number | null>(null)
  const releaseRef = useRef<(() => void) | null>(null)
  const unwindTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // True from the moment an unwind is decided until its move has landed (or turned out unnecessary).
  const unwindingRef = useRef(false)
  // The overlay reopened while its old entry was still being unwound: push once that has landed.
  const pushAfterUnwindRef = useRef(false)
  // This overlay opened while another's move was in flight: its push is queued behind that move, once.
  const pushQueuedRef = useRef(false)
  const openRef = useRef(open)
  const mountedRef = useRef(true)
  const dismissibleRef = useRef(dismissible)
  const onCloseRef = useRef(onClose)
  const navigateRef = useRef(navigate)
  const locationRef = useRef(location)
  openRef.current = open
  dismissibleRef.current = dismissible
  onCloseRef.current = onClose
  navigateRef.current = navigate
  locationRef.current = location

  // Bookkeeping only: the browser has already popped the entry, so there is
  // nothing to unwind. Used when a real back press closes the overlay.
  function discardEntry() {
    hasEntryRef.current = false
    pushedIdxRef.current = null
    pushedIdRef.current = null
    releaseRef.current?.()
    releaseRef.current = null
    stopListeningIfIdle()
  }

  function pushEntry() {
    const id = nextDialogId++
    pushedIdxRef.current = (historyIndexOf(window.history.state) ?? 0) + 1
    pushedIdRef.current = id
    const at = locationRef.current
    navigateRef.current(at, {
      state: { ...(at.state as Record<string, unknown> | null), lemelyDialog: true, lemelyDialogId: id },
      // This push is same-URL bookkeeping, not real navigation — but
      // `scrollRestorationKey` cannot tell the difference from a real push
      // on a non-tab-root screen (both change `location.key`). Without
      // this, opening a dialog scrolls the page to the top.
      preventScrollReset: true,
    })
    hasEntryRef.current = true
    releaseRef.current = dialogHistoryStack.register({
      isDismissible: () => dismissibleRef.current,
      close: () => {
        discardEntry()
        onCloseRef.current()
      },
      isCurrent: () => isDialogEntry(window.history.state, pushedIdxRef.current, pushedIdRef.current),
      repush: () => {
        dialogHistoryStack.expectSelfPop((historyIndexOf(window.history.state) ?? 0) + 1)
        navigateRef.current(1)
      },
    })
    startListening()
  }

  // One overlay handing over to another in a single commit (a menu item closes the menu and opens a
  // sheet): the closing overlay's `navigate(-1)` is still in flight when this one opens. A push now would
  // go in before that move lands. Chromium fixes the move's target when it is issued, so it would land
  // below the new entry and leave this overlay open with no current entry (the next Back leaves the
  // page); resolved on landing instead, it would stop on the old entry and read as a real Back, closing
  // this overlay at once. Push once the cursor has settled.
  function pushWhenCursorSettles() {
    if (!dialogHistoryStack.hasPendingSelfPop()) {
      pushEntry()
      return
    }
    if (pushQueuedRef.current) return
    pushQueuedRef.current = true
    dialogHistoryStack.afterNextSelfPop(() => {
      pushQueuedRef.current = false
      if (mountedRef.current && openRef.current && !hasEntryRef.current) pushWhenCursorSettles()
    })
  }

  // The old entry is gone (or never needed to go): a reopen that waited for that can push now.
  function settleUnwind() {
    unwindingRef.current = false
    if (!pushAfterUnwindRef.current) return
    pushAfterUnwindRef.current = false
    if (mountedRef.current && openRef.current && !hasEntryRef.current) pushEntry()
  }

  function unwindEntry() {
    const pushedIdx = pushedIdxRef.current
    const pushedId = pushedIdRef.current
    discardEntry()
    unwindingRef.current = true
    // Read the live history entry rather than this render's `location`: on
    // unmount the last render is one navigation behind. Unwind only when the
    // current entry is still the one we pushed (this index AND this push's id);
    // otherwise the reader has navigated, replaced it, or a newer dialog sits
    // there, and `navigate(-1)` would undo that.
    const unwind = () => {
      if (pushedIdx === null || !isDialogEntry(window.history.state, pushedIdx, pushedId)) {
        settleUnwind()
        return
      }
      // The listener may have been dropped when the stack emptied; the popstate of this move must be heard.
      startListening()
      dialogHistoryStack.expectSelfPop(pushedIdx - 1, settleUnwind)
      navigateRef.current(-1)
    }
    // Stacked overlays closing in one tick: the overlay above is popping (or about to), so the live entry
    // is its entry, not ours. Wait for that popstate, then read again.
    if (dialogHistoryStack.hasPendingSelfPop() || dialogHistoryStack.topEntryIsCurrent()) dialogHistoryStack.afterNextSelfPop(unwind)
    else unwind()
  }

  const unwindRef = useRef(unwindEntry)
  unwindRef.current = unwindEntry

  // Open/close transitions: push on open, unwind on programmatic close.
  useEffect(() => {
    mountedRef.current = true
    if (unwindTimerRef.current !== null) {
      clearTimeout(unwindTimerRef.current)
      unwindTimerRef.current = null
    }

    const action = nextDialogHistoryAction({
      event: open ? "open" : "close",
      dismissible: dismissibleRef.current,
      hasEntry: hasEntryRef.current,
    })

    if (action === "push") {
      // Reopened while the old entry is still being unwound: pushing now would stack a new entry on the
      // old one and the unwind's `navigate(-1)` would land on the wrong one. Push once it has landed.
      if (unwindingRef.current) {
        pushAfterUnwindRef.current = true
        return
      }
      pushWhenCursorSettles()
      return
    }

    if (action === "pop") unwindEntry()
    else if (!open) pushAfterUnwindRef.current = false
    // `navigate`/`location` intentionally excluded: this must run only on
    // `open` transitions, not on every render caused by router state
    // changing (including the very push/pop this effect itself performs).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Unmount: an overlay torn down while still open (its screen navigated
  // away, its parent stopped rendering it) must not leave its pushed entry
  // behind — an orphaned entry makes the reader's next back press appear to
  // do nothing at all, since the entry sits at the same URL.
  useEffect(() => {
    return () => {
      mountedRef.current = false
      if (!hasEntryRef.current) return
      // Deferred a tick so React StrictMode's development remount — cleanup
      // immediately followed by the effect above re-running, which clears
      // this timer — does not unwind and re-push a live entry.
      unwindTimerRef.current = setTimeout(() => unwindRef.current(), 0)
    }
  }, [])
}
