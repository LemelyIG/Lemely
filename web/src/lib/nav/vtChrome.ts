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

export function installVtChrome(router: RouterLike, root: HTMLElement = document.documentElement): () => void {
  let lastKey = router.state.location.key
  let lastMatches = router.state.matches
  return router.subscribe((state) => {
    // Loading states and fetchers re-publish the same location; only a location change is a hop.
    if (state.location.key === lastKey) return
    if (hopCrossesImmersive(lastMatches, state.matches)) root.dataset.vtChrome = "page"
    else delete root.dataset.vtChrome
    lastKey = state.location.key
    lastMatches = state.matches
  })
}
