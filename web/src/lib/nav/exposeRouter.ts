/*
 * The router, on `window`, for the drift and behaviour harness only.
 *
 * A check that drives a programmatic `navigate()` (a button, not a Link) needs the router. It used
 * to find it by walking React's private fiber tree, which breaks with any React internals change.
 * This is the supported seam instead: present in the dev server, and in a production build only
 * when the harness set `window.__LEMELY_DRIFT__` before the app loaded (`scripts/drift/harness.mjs`
 * does, through an init script). A student's or teacher's browser sets neither, and the router is no more
 * powerful than typing a URL.
 */
export const DRIFT_FLAG = "__LEMELY_DRIFT__"

/** Any router: the harness calls `navigate` on it from a page script. */
export interface ExposedRouter {
  navigate: unknown
}

export function exposeRouterForChecks(router: ExposedRouter, scope: Record<string, unknown> | undefined = typeof window === "undefined" ? undefined : (window as unknown as Record<string, unknown>)): boolean {
  if (!scope) return false
  if (!import.meta.env.DEV && scope[DRIFT_FLAG] !== true) return false
  scope.__lemelyRouter = router
  return true
}
