import type { MouseEvent } from "react"
import { parsePath, resolvePath, useNavigate, useResolvedPath, type NavigateOptions, type To } from "react-router-dom"
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

/** `?` and `#` alone are empty, and a bare `x` is `?x` / `#x` (React Router's `normalizeSearch` and `normalizeHash`). */
const normSearch = (search: string | undefined) => (!search || search === "?" ? "" : search.startsWith("?") ? search : `?${search}`)
const normHash = (hash: string | undefined) => (!hash || hash === "#" ? "" : hash.startsWith("#") ? hash : `#${hash}`)

/**
 * A pathname as the router matches it: percent-encoding decoded (`matchRoutes` runs `decodeURI`, so `/a%20b`
 * and `/a b` are one route) and no trailing slash (`/a/` matches the `/a` route). Case stays: a param
 * (`/tutors/ABC`) is a different page from `/tutors/abc`.
 */
function routerPathname(pathname: string): string {
  let decoded = pathname
  try {
    decoded = decodeURI(pathname)
  } catch {
    // A malformed escape is compared as written.
  }
  const trimmed = decoded.replace(/\/+$/, "")
  return trimmed === "" ? "/" : trimmed
}

/** Does `to` carry no pathname at all (`"?x"`, `"#x"`, `{ search }`)? Only then does React Router resolve it against the address bar; `""` and `{ pathname: "" }` stay relative to the route. */
function isPathless(to: To): boolean {
  if (to === "") return false
  const pathname = typeof to === "string" ? parsePath(to).pathname : to.pathname
  return pathname === undefined || pathname === null
}

/**
 * Would `navigate(to)` land on the URL the reader is already at? Path, search AND hash must all
 * match: `#section` on the same page is a destination, not a no-op. `basePathname` is what a relative
 * `to` resolves against. React Router resolves `navigate("sibling")` against the calling route's
 * pathname (not the address bar's), so the caller passes that. A `to` with no pathname (`"?x"`, `"#x"`,
 * an object without `pathname`) resolves against the current URL instead, as React Router does.
 * Paths compare as the router matches them: percent-encoding decoded, trailing slash ignored.
 */
export function isSameUrl(
  to: To,
  basePathname: string,
  current: { pathname: string; search: string; hash: string },
): boolean {
  const target = resolvePath(to, isPathless(to) ? current.pathname : basePathname)
  return (
    routerPathname(target.pathname) === routerPathname(current.pathname) &&
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
