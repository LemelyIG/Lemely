/*
 * One place that composes wrappers around `router.navigate`. Several features need to see every
 * navigation before it runs (the swipe-back snapshot clones the page being left; a native push
 * default adjusts the options). If each monkey-patched `navigate` on its own, the order would be
 * whichever module happened to import first. Here the order is explicit and tested.
 *
 * Rules:
 * - Each middleware wraps the router's CURRENT `navigate`, never a saved original, so a wrapper
 *   installed later, or by someone else, stays in the chain.
 * - Within one `installNavigateMiddleware` call the list runs in order: the first entry runs first
 *   and calls `next` to reach the second, and the last calls the router's own navigate.
 * - A separate, later install wraps outside everything installed before it, so it runs first.
 * - Installing the same middleware on the same router twice is a no-op.
 *
 * INSTALL AT MODULE LOAD, before the first render (`App.tsx`, right after `createBrowserRouter`).
 * `useSubmit` and `<Form>` read `router.navigate` once per render and keep that function, so a
 * wrapper installed after a component has rendered is invisible to its form submissions. Never
 * install from an effect, a component body, or a lazy route.
 */

export type NavigateOptions = { replace?: boolean; [key: string]: unknown }
export type NavigateFn = (to: unknown, options?: NavigateOptions) => unknown
/** Read or adjust `options`, then call `next(to, options)` to continue the chain. */
export type NavigateMiddleware = (to: unknown, options: NavigateOptions | undefined, next: NavigateFn) => unknown

const installed = new WeakMap<object, Set<NavigateMiddleware>>()

export function installNavigateMiddleware(router: { navigate: unknown }, middlewares: readonly NavigateMiddleware[]): void {
  let seen = installed.get(router)
  if (!seen) {
    seen = new Set()
    installed.set(router, seen)
  }
  const fresh = middlewares.filter((mw) => !seen.has(mw))
  // Wrap from the last to the first, so the first ends up outermost and runs first.
  for (const mw of [...fresh].reverse()) {
    seen.add(mw)
    const current = router.navigate as NavigateFn
    router.navigate = (to: unknown, options?: NavigateOptions) => mw(to, options, current)
  }
}
