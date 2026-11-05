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
  /**
   * The background entry's react-router history index (`history.state.idx`),
   * when known. Closing steps back exactly to that entry, however many
   * entries the reader has walked since (`overlayCloseAction`).
   */
  backgroundIdx?: number
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

/** Reads `state.backgroundIdx`, or `null` when it is missing or not a
 * non-negative integer. */
export function readBackgroundIdx(state: unknown): number | null {
  if (!isRecord(state)) return null
  const idx = state.backgroundIdx
  return typeof idx === "number" && Number.isInteger(idx) && idx >= 0 ? idx : null
}

/** react-router's own entry index (`window.history.state.idx`) read from a
 * `history.state` value, or `null` when it is absent. */
export function historyIndexOf(historyState: unknown): number | null {
  if (!isRecord(historyState)) return null
  const idx = historyState.idx
  return typeof idx === "number" && Number.isInteger(idx) ? idx : null
}

/** Builds the `state` a navigation into an overlay route should carry. */
export function backgroundState(
  location: BackgroundLocation,
  backgroundIdx: number | null = null,
): BackgroundState {
  const state: BackgroundState = {
    backgroundLocation: {
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
    },
  }
  if (backgroundIdx !== null) state.backgroundIdx = backgroundIdx
  return state
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

export type OverlayCloseAction = { kind: "go"; delta: number } | { kind: "replace"; to: string }

/**
 * What closing the overlay does.
 *
 * When the state records the background entry's history index and that entry
 * is behind the current one, closing walks back to it (`go(delta)`, delta
 * negative): Back and the close button then land on the same entry, even
 * after the reader left the dialog for another page and came back with Back
 * (where a blind `go(-1)` would land on that other page). Otherwise (a deep
 * link, a fresh tab, an index that is not behind us) closing replaces the
 * overlay entry with the background page, or the fallback when there is none.
 */
export function overlayCloseAction(input: {
  state: unknown
  historyIndex: number | null
  overlayBase: string
  fallbackPath: string
}): OverlayCloseAction {
  const background = readBackgroundLocation(input.state)
  const usable = background && !isWithinBase(background.pathname, input.overlayBase)
  if (!usable) return { kind: "replace", to: input.fallbackPath }
  const backgroundIdx = readBackgroundIdx(input.state)
  if (backgroundIdx !== null && input.historyIndex !== null) {
    const delta = backgroundIdx - input.historyIndex
    if (delta < 0) return { kind: "go", delta }
  }
  return { kind: "replace", to: `${background.pathname}${background.search}${background.hash}` }
}

/**
 * Everything the overlay outlet decides for one render, as data.
 *
 * - `screenLocation`: the location the page slot matches its routes
 *   against, and what that page's `useLocation()` returns. Outside the
 *   overlay it is the current location, router state and key included (the
 *   teacher home hands dropped papers to Grading in `state`); inside, the
 *   background. Either way the page renders through one element, so opening
 *   or closing the overlay never remounts the page underneath.
 * - `replaceState`: router state to write onto the current (overlay) entry
 *   with a same-URL replace, or `null`. Written when the entry lacks a
 *   background (a plain link: the remembered page goes in) or lacks the
 *   background's history index (a link whose background matches the page we
 *   just showed), so a refresh keeps the same page underneath and closing can
 *   walk back to it. Never written on a deep link (nothing to remember).
 */
export function planOverlayOutlet(input: {
  location: BackgroundLocation & { state: unknown; key?: string }
  remembered: BackgroundLocation | null
  rememberedIdx: number | null
  overlayBase: string
  fallbackPath: string
}): {
  inOverlay: boolean
  screenLocation: BackgroundLocation & { state?: unknown; key?: string }
  background: ReturnType<typeof resolveBackground> | null
  replaceState: BackgroundState | null
} {
  const { location } = input
  if (!isWithinBase(location.pathname, input.overlayBase)) {
    const { pathname, search, hash, state, key } = location
    return { inOverlay: false, screenLocation: { pathname, search, hash, state, key }, background: null, replaceState: null }
  }
  const background = resolveBackground({
    state: location.state,
    remembered: input.remembered,
    overlayBase: input.overlayBase,
    fallbackPath: input.fallbackPath,
  })
  let replaceState: BackgroundState | null = null
  if (background.source === "remembered") {
    replaceState = backgroundState(background.location, input.rememberedIdx)
  } else if (
    background.source === "state" &&
    readBackgroundIdx(location.state) === null &&
    input.rememberedIdx !== null &&
    input.remembered !== null &&
    sameLocation(input.remembered, background.location)
  ) {
    replaceState = { ...(location.state as object), ...backgroundState(background.location, input.rememberedIdx) }
  }
  return { inOverlay: true, screenLocation: background.location, background, replaceState }
}

function sameLocation(a: BackgroundLocation, b: BackgroundLocation): boolean {
  return a.pathname === b.pathname && a.search === b.search && a.hash === b.hash
}
