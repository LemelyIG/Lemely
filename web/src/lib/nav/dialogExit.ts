import type { MouseEvent } from "react"
import { resolvePath, useNavigate, type NavigateOptions, type To } from "react-router-dom"
import { dialogHistoryStack } from "@/lib/nav/dialogHistoryStack"

/*
 * Leaving an open dialog for another screen.
 *
 * Opening a sheet, Modal or NavDrawer pushes a `lemelyDialog` entry. A link
 * inside it that pushed on top would leave that entry as an orphan
 * ([origin, dialog, destination]) and every later Back would hit a dead
 * press. So while the current entry IS the top dialog's own entry, the
 * navigation replaces it: [origin, destination], and one Back returns to the
 * origin. A destination equal to the current URL is not navigated to at all:
 * the dialog is simply popped, as Back would.
 *
 * The decision reads the live history state at click time, never a render's.
 */

function sameUrl(to: To): boolean {
  const target = resolvePath(to, window.location.pathname)
  const norm = (search: string) => (search === "?" ? "" : search)
  return target.pathname === window.location.pathname && norm(target.search) === norm(window.location.search)
}

/** `navigate`, but a navigation out of an open dialog replaces its entry. */
export function useDialogExitNavigate(): (to: To, options?: NavigateOptions) => void {
  const navigate = useNavigate()
  return (to, options) => {
    if (!dialogHistoryStack.topEntryIsCurrent()) {
      void navigate(to, options)
      return
    }
    if (sameUrl(to) && !options?.state) {
      window.history.back()
      return
    }
    void navigate(to, { ...options, replace: true })
  }
}

/** A `Link`/`NavLink` `onClick` that routes a click inside a dialog through `useDialogExitNavigate`. */
export function useDialogExitClick(
  to: To,
  options?: NavigateOptions,
): (event: MouseEvent<HTMLElement>) => void {
  const go = useDialogExitNavigate()
  return (event) => {
    if (event.defaultPrevented || event.button !== 0) return
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    if (!dialogHistoryStack.topEntryIsCurrent()) return
    event.preventDefault()
    go(to, options)
  }
}
