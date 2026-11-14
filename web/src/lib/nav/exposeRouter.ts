/*
 * The router, on `window`, for the drift and behaviour harness only.
 *
 * A check that drives a programmatic `navigate()` (a button, not a Link) needs the router. It used
 * to find it by walking React's private fiber tree, which breaks with any React internals change.
 * This is the supported seam instead: present in the dev server, and in a production build only
 * when the build itself was made with `VITE_LEMELY_DRIFT=1` (`npm run build:drift`, which the
 * harness's runs use). Vite replaces `import.meta.env.VITE_LEMELY_DRIFT` at build time, so in a
 * deployed build the condition below is constant-false and this module's body is tree-shaken: a
 * student's or teacher's browser carries no hook at all.
 */
export const DRIFT_BUILD = import.meta.env.VITE_LEMELY_DRIFT === "1"

/** Any router: the harness calls `navigate` on it from a page script. */
export interface ExposedRouter {
  navigate: unknown
}

export function exposeRouterForChecks(router: ExposedRouter, scope: Record<string, unknown> | undefined = typeof window === "undefined" ? undefined : (window as unknown as Record<string, unknown>)): boolean {
  if (!scope) return false
  if (!import.meta.env.DEV && !DRIFT_BUILD) return false
  scope.__lemelyRouter = router
  return true
}
