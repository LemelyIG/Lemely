import type { MouseEvent } from "react"
import { resolvePath, useNavigate, useResolvedPath, type NavigateOptions, type To } from "react-router-dom"
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

/** `?` and `#` alone are empty. */
const normSearch = (search: string) => (search === "?" ? "" : search)
const normHash = (hash: string) => (hash === "#" ? "" : hash)

/**
 * Would `navigate(to)` land on the URL the reader is already at? Path, search AND hash must all
 * match: `#section` on the same page is a destination, not a no-op. `basePathname` is what a relative
 * `to` resolves against. React Router resolves `navigate("sibling")` against the calling route's
 * pathname (not the address bar's), so the caller passes that.
 */
export function isSameUrl(
  to: To,
  basePathname: string,
  current: { pathname: string; search: string; hash: string },
): boolean {
  const target = resolvePath(to, basePathname)
  return (
    target.pathname === current.pathname &&
    normSearch(target.search) === normSearch(current.search) &&
    normHash(target.hash) === normHash(current.hash)
  )
}

/** `navigate`, but a navigation out of an open dialog replaces its entry. */
export function useDialogExitNavigate(): (to: To, options?: NavigateOptions) => void {
  const navigate = useNavigate()
  const route = useResolvedPath(".")
  return (to, options) => {
    if (!dialogHistoryStack.topEntryIsCurrent()) {
      void navigate(to, options)
      return
    }
    // `relative: "path"` resolves against the address bar; the default resolves against the route.
    const base = options?.relative === "path" ? window.location.pathname : route.pathname
    // A navigation that carries state is a destination even at this URL: popping would drop it.
    if (isSameUrl(to, base, window.location) && options?.state === undefined) {
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
