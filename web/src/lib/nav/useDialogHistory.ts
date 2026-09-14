import { useEffect, useRef } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { nextDialogHistoryAction } from "@/lib/nav/dialogHistory"
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
 * One case the plain push/pop pairing gets wrong on its own: `NavDrawer`
 * also closes itself when the *route* changes (tapping a link inside it —
 * see `nav-drawer.tsx`'s own "close on navigation" effect). That real
 * navigation pushes its own entry, landing the browser past the dialog's
 * pushed entry. If this hook still answered that close by calling
 * `navigate(-1)`, it would undo the navigation the reader just asked for
 * rather than merely dismiss the drawer. `openedAtPathRef` guards this: it
 * records the pathname+search the entry was pushed against, and a close is
 * only unwound with `navigate(-1)` when the reader is still on that same
 * route — if the route has already moved on, the pushed entry is treated as
 * spent and left in the stack rather than backed out of.
 */

let listening = false

function onWindowPopState() {
  dialogHistoryStack.handlePopState()
}

function startListening() {
  if (listening) return
  window.addEventListener("popstate", onWindowPopState)
  listening = true
}

function stopListeningIfIdle() {
  if (!listening || dialogHistoryStack.size > 0) return
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
  const openedAtPathRef = useRef<string | null>(null)
  const releaseRef = useRef<(() => void) | null>(null)
  const unwindTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const dismissibleRef = useRef(dismissible)
  const onCloseRef = useRef(onClose)
  const navigateRef = useRef(navigate)
  dismissibleRef.current = dismissible
  onCloseRef.current = onClose
  navigateRef.current = navigate

  // Bookkeeping only: the browser has already popped the entry, so there is
  // nothing to unwind. Used when a real back press closes the overlay.
  function discardEntry() {
    hasEntryRef.current = false
    openedAtPathRef.current = null
    releaseRef.current?.()
    releaseRef.current = null
    stopListeningIfIdle()
  }

  function unwindEntry() {
    const openedAt = openedAtPathRef.current
    discardEntry()
    // Read the live URL rather than this render's `location`: on unmount the
    // last render is one navigation behind, and unwinding then would undo the
    // navigation that unmounted us.
    if (window.location.pathname + window.location.search !== openedAt) return
    dialogHistoryStack.expectSelfPop()
    navigateRef.current(-1)
  }

  const unwindRef = useRef(unwindEntry)
  unwindRef.current = unwindEntry

  // Open/close transitions: push on open, unwind on programmatic close.
  useEffect(() => {
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
      openedAtPathRef.current = location.pathname + location.search
      navigate(location, {
        state: { ...(location.state as Record<string, unknown> | null), lemelyDialog: true },
      })
      hasEntryRef.current = true
      releaseRef.current = dialogHistoryStack.register({
        isDismissible: () => dismissibleRef.current,
        close: () => {
          discardEntry()
          onCloseRef.current()
        },
        repush: () => {
          dialogHistoryStack.expectSelfPop()
          navigateRef.current(1)
        },
      })
      startListening()
      return
    }

    if (action === "pop") unwindEntry()
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
      if (!hasEntryRef.current) return
      // Deferred a tick so React StrictMode's development remount — cleanup
      // immediately followed by the effect above re-running, which clears
      // this timer — does not unwind and re-push a live entry.
      unwindTimerRef.current = setTimeout(() => unwindRef.current(), 0)
    }
  }, [])
}
