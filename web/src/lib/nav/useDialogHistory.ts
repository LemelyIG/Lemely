import { useEffect, useRef } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { nextDialogHistoryAction } from "@/lib/nav/dialogHistory"

/*
 * Packet B2a · wires `nextDialogHistoryAction`'s decision table into an
 * actual history entry for `Modal` and `NavDrawer`.
 *
 * Opening pushes one entry (`state.lemelyDialog: true`, URL unchanged) so
 * browser back closes the overlay instead of navigating the page underneath
 * it away. Programmatic close (`onClose`/scrim/Escape/footer action) unwinds
 * that same entry with `navigate(-1)` — a `poppingRef` guard means the
 * popstate this produces is recognised as "our own unwind" and does not
 * re-trigger `onClose`. A `ConfirmModal` (`dismissible={false}`) re-pushes
 * on a browser-back popstate instead of closing, so a stray back gesture
 * cannot silently answer a destructive confirmation.
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
  const poppingRef = useRef(false)
  const openedAtPathRef = useRef<string | null>(null)
  const dismissibleRef = useRef(dismissible)
  const onCloseRef = useRef(onClose)
  dismissibleRef.current = dismissible
  onCloseRef.current = onClose

  // Open/close transitions: push on open, unwind on programmatic close.
  useEffect(() => {
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
      return
    }

    if (action === "pop") {
      hasEntryRef.current = false
      const stillOnOpenedRoute = location.pathname + location.search === openedAtPathRef.current
      openedAtPathRef.current = null
      if (!stillOnOpenedRoute) return
      poppingRef.current = true
      navigate(-1)
    }
    // `navigate`/`location` intentionally excluded: this must run only on
    // `open` transitions, not on every render caused by router state
    // changing (including the very push/pop this effect itself performs).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Browser back while an entry is pending.
  useEffect(() => {
    function handlePopState() {
      if (poppingRef.current) {
        // Our own navigate(-1) from the effect above — already handled.
        poppingRef.current = false
        return
      }

      const action = nextDialogHistoryAction({
        event: "popstate",
        dismissible: dismissibleRef.current,
        hasEntry: hasEntryRef.current,
      })

      if (action === "closeOnly") {
        hasEntryRef.current = false
        openedAtPathRef.current = null
        onCloseRef.current()
      } else if (action === "repush") {
        navigate(1)
      }
    }

    window.addEventListener("popstate", handlePopState)
    return () => window.removeEventListener("popstate", handlePopState)
  }, [navigate])
}
