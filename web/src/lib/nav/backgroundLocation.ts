/*
 * The background-location pattern for route-backed overlays.
 *
 * A route like `/teacher/settings/notifications` is a real URL (deep links,
 * refresh and Back all work), but it renders as a dialog over whatever page
 * the reader was on. The page underneath is carried in router state as
 * `backgroundLocation`; the layout renders that location's screen behind the
 * dialog. A direct load has no such state, so the overlay falls back to a
 * fixed page (the portal home).
 *
 * Everything here is pure, so the decisions (which page sits underneath,
 * what closing does) are unit-testable without a DOM.
 */

/** The parts of a router location this pattern needs. */
export interface BackgroundLocation {
  pathname: string
  search: string
  hash: string
}

/** What a link or navigation into an overlay route carries as `state`. */
export interface BackgroundState {
  backgroundLocation: BackgroundLocation
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

/** `true` when `pathname` is `base` itself or anything below it. */
export function isWithinBase(pathname: string, base: string): boolean {
  const trimmed = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
  return trimmed === base || trimmed.startsWith(`${base}/`)
}

/**
 * Reads `state.backgroundLocation`, or `null` when it is missing or not
 * shaped like a location. Router state survives a refresh but is otherwise
 * untyped, so it is validated rather than trusted.
 */
export function readBackgroundLocation(state: unknown): BackgroundLocation | null {
  if (!isRecord(state)) return null
  const candidate = state.backgroundLocation
  if (!isRecord(candidate)) return null
  const { pathname, search, hash } = candidate
  if (typeof pathname !== "string" || !pathname.startsWith("/")) return null
  return {
    pathname,
    search: typeof search === "string" ? search : "",
    hash: typeof hash === "string" ? hash : "",
  }
}

/** Builds the `state` a navigation into an overlay route should carry. */
export function backgroundState(location: BackgroundLocation): BackgroundState {
  return {
    backgroundLocation: {
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
    },
  }
}

/**
 * Which page sits underneath the overlay.
 *
 * In order: the location carried in router state, then the last page the
 * reader was on in this session (for links that open the overlay without
 * state), then `fallbackPath`. A candidate inside the overlay's own base is
 * skipped, so the overlay can never be its own background.
 */
export function resolveBackground(input: {
  state: unknown
  remembered: BackgroundLocation | null
  overlayBase: string
  fallbackPath: string
}): { location: BackgroundLocation; source: "state" | "remembered" | "fallback" } {
  const fromState = readBackgroundLocation(input.state)
  if (fromState && !isWithinBase(fromState.pathname, input.overlayBase)) {
    return { location: fromState, source: "state" }
  }
  if (input.remembered && !isWithinBase(input.remembered.pathname, input.overlayBase)) {
    return { location: input.remembered, source: "remembered" }
  }
  return { location: { pathname: input.fallbackPath, search: "", hash: "" }, source: "fallback" }
}

/**
 * The pathname that names "the page" for chrome such as a title or trail.
 * While an overlay is open that is the page underneath it (from router
 * state), not the overlay's own URL; otherwise it is `pathname` itself.
 */
export function underlyingPathname(input: {
  pathname: string
  state: unknown
  overlayBase: string
}): string {
  if (!isWithinBase(input.pathname, input.overlayBase)) return input.pathname
  const background = readBackgroundLocation(input.state)
  if (background && !isWithinBase(background.pathname, input.overlayBase)) {
    return background.pathname
  }
  return input.pathname
}

export type OverlayCloseAction = { kind: "back" } | { kind: "replace"; to: string }

/**
 * What closing the overlay does.
 *
 * With a background in state and an entry behind this one, closing is a
 * history step back: the page underneath is exactly the previous entry, so
 * Back and the close button agree. Otherwise (a deep link, a fresh tab) there
 * is nothing behind to step back to, and closing replaces the overlay entry
 * with the background page or the fallback.
 */
export function overlayCloseAction(input: {
  state: unknown
  historyIndex: number | null
  overlayBase: string
  fallbackPath: string
}): OverlayCloseAction {
  const background = readBackgroundLocation(input.state)
  const usable = background && !isWithinBase(background.pathname, input.overlayBase)
  if (usable && input.historyIndex !== null && input.historyIndex > 0) return { kind: "back" }
  if (usable) {
    return { kind: "replace", to: `${background.pathname}${background.search}${background.hash}` }
  }
  return { kind: "replace", to: input.fallbackPath }
}
