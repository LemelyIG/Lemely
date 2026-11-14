/*
 * NF motion · which hops carry the tab bar in the page snapshot instead of as its own transition
 * group. The native tab bar is hidden on immersive routes (`handle.immersive`), so on a hop into or
 * out of one its `lm-chrome-tabs` group would exist on one side only: it would vanish at frame 0
 * going in and paint above the leaving page coming back. `html[data-vt-chrome="page"]` drops the
 * bar's view-transition-name (index.css), so it rides with its page, as UIKit's
 * hidesBottomBarWhenPushed does.
 *
 * The attribute must exist before React Router calls `document.startViewTransition`, which takes the
 * old snapshot; a layout effect in RootOutlet runs after it. `installVtChrome` therefore subscribes to
 * the router before `RouterProvider` mounts (RR's own subscriber, which starts the transition, is
 * registered in a layout effect and so runs after ours). It covers POPs, since it reads the
 * location change itself.
 */
interface MatchLike {
  route: { handle?: unknown }
}

export function isImmersive(matches: readonly MatchLike[]): boolean {
  return matches.some((m) => (m.route.handle as { immersive?: boolean } | undefined)?.immersive === true)
}

/** True when a hop enters or leaves an immersive route. */
export function hopCrossesImmersive(prev: readonly MatchLike[], next: readonly MatchLike[]): boolean {
  return isImmersive(prev) !== isImmersive(next)
}

interface RouterLike {
  state: { location: { key: string }; matches: readonly MatchLike[] }
  subscribe(listener: (state: { location: { key: string }; matches: readonly MatchLike[] }) => void): () => void
}

/**
 * The matches the DOM is showing right now. The router's own state moves on commit; the screen on
 * paint can lag it. When a second hop interrupts a first before React rendered it, "the page I am
 * leaving" is the one still painted, not the matches of the interrupted hop. RootOutlet reports what
 * it rendered here; until it has, the last committed matches stand in.
 */
let rendered: readonly MatchLike[] | null = null

export function noteRenderedMatches(matches: readonly MatchLike[]): void {
  rendered = matches
}

/** How long a set attribute may outlive its hop when no view transition ever claims it (no VT support, an aborted navigation). */
const CLEAR_FALLBACK_MS = 3000

interface ViewTransitionHost {
  startViewTransition?: (...args: unknown[]) => { finished: Promise<unknown> } | undefined
}

export function installVtChrome(
  router: RouterLike,
  root: HTMLElement = document.documentElement,
  host: ViewTransitionHost | undefined = typeof document === "undefined" ? undefined : (document as unknown as ViewTransitionHost),
): () => void {
  let lastKey = router.state.location.key
  let lastMatches = router.state.matches
  // Each hop that sets the attribute gets a token; a clear only counts for the hop it belongs to, so
  // the end of an old transition cannot wipe the attribute a newer hop just set.
  let token = 0
  let fallback: ReturnType<typeof setTimeout> | undefined
  const clear = (own: number) => {
    if (own !== token) return
    delete root.dataset.vtChrome
  }

  // The attribute lives for the transition it was set for: clear it when that transition finishes.
  // React Router starts the transition after our subscriber, so wrapping the host method is the one
  // place that sees it.
  const real = host?.startViewTransition
  if (host && real) {
    host.startViewTransition = function (this: unknown, ...args: unknown[]) {
      const transition = real.apply(host, args)
      const own = token
      if (root.dataset.vtChrome && transition?.finished) void transition.finished.then(() => clear(own), () => clear(own))
      return transition
    }
  }

  const unsubscribe = router.subscribe((state) => {
    // Loading states and fetchers re-publish the same location; only a location change is a hop.
    if (state.location.key === lastKey) return
    token += 1
    clearTimeout(fallback)
    if (hopCrossesImmersive(rendered ?? lastMatches, state.matches)) {
      root.dataset.vtChrome = "page"
      const own = token
      fallback = setTimeout(() => clear(own), CLEAR_FALLBACK_MS)
    } else delete root.dataset.vtChrome
    lastKey = state.location.key
    lastMatches = state.matches
  })
  return () => {
    unsubscribe()
    clearTimeout(fallback)
    if (host && real) host.startViewTransition = real
  }
}
