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

interface LocationLike {
  key: string
  pathname?: string
}

interface RouterLike {
  state: { location: LocationLike; matches: readonly MatchLike[] }
  subscribe(listener: (state: { location: LocationLike; matches: readonly MatchLike[] }) => void): () => void
}

/** The native phone frame: a phone-width viewport on iOS or Android (`useNativeFrame`'s rule, read without React). */
function nativeFrameNow(root: HTMLElement): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false
  const platform = root.dataset.platform
  return (platform === "ios" || platform === "android") && window.matchMedia("(max-width: 720px)").matches
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
  startViewTransition?: (...args: unknown[]) => { finished: Promise<unknown>; skipTransition?: () => void } | undefined
}

export function installVtChrome(
  router: RouterLike,
  root: HTMLElement = document.documentElement,
  host: ViewTransitionHost | undefined = typeof document === "undefined" ? undefined : (document as unknown as ViewTransitionHost),
  isNative: () => boolean = () => nativeFrameNow(root),
): () => void {
  let lastKey = router.state.location.key
  let lastMatches = router.state.matches
  let lastPathname = router.state.location.pathname
  // Did the hop being committed keep the pathname? A dialog or sheet closing is a same-URL POP, and React
  // Router replays a view transition on any POP whose destination ever started one: the page would slide onto itself.
  let samePath = false
  // Two tokens. Each hop that sets the attribute gets a hop token. Each view transition that takes the
  // attribute over gets a claim token. A clear counts only when it is the newest claim of the newest hop:
  // the end of an old transition, or of a transition a newer one has since replaced (two hops committing
  // back to back), cannot wipe the attribute the newer one is still carrying.
  let token = 0
  let claims = 0
  let fallback: ReturnType<typeof setTimeout> | undefined
  const clear = (own: number, claim?: number) => {
    if (own !== token || (claim !== undefined && claim !== claims)) return
    delete root.dataset.vtChrome
  }

  // The attribute lives for the transition it was set for: clear it when that transition finishes.
  // React Router starts the transition after our subscriber, so wrapping the host method is the one
  // place that sees it.
  const real = host?.startViewTransition
  if (host && real) {
    host.startViewTransition = function (this: unknown, ...args: unknown[]) {
      // Read before the call: the hop this transition belongs to is the one whose flag is set right now.
      const own = token
      const carries = Boolean(root.dataset.vtChrome)
      const transition = real.apply(host, args)
      // Native frame only: desktop and tablet keep their transitions unchanged.
      if (samePath && isNative()) transition?.skipTransition?.()
      if (carries && transition?.finished) {
        // A transition has the flag now, and its `finished` ends it: the fallback is for hops nobody claims.
        clearTimeout(fallback)
        const claim = ++claims
        void transition.finished.then(() => clear(own, claim), () => clear(own, claim))
      }
      return transition
    }
  }

  const unsubscribe = router.subscribe((state) => {
    // Loading states and fetchers re-publish the same location; only a location change is a hop.
    if (state.location.key === lastKey) return
    token += 1
    samePath = state.location.pathname !== undefined && state.location.pathname === lastPathname
    lastPathname = state.location.pathname
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
