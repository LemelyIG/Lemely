/*
 * Task 5 (B4a) · the pure decision `usePullToRefresh` (`useDragGesture` with
 * `axis: "y"`) reduces a drag to, same split as `dragMath.ts`: a 0..1
 * progress for the indicator, and a yes/no for whether release should call
 * `onRefresh`. Kept dependency-free and out of the hook itself so it is
 * reachable from a Node-only unit test (`vitest.config.ts` runs with no
 * jsdom, D3.20).
 */

/**
 * How far a downward pull at the scroll top has travelled, as a 0..1
 * fraction of `threshold`, and whether it has gone far enough to arm a
 * refresh on release. Not at the scroll top, or pulling in the wrong
 * direction (`dy <= 0` — pushing up, or no movement), always reads as no
 * pull at all: this is what lets a normal downward drag lower in a list (not
 * at `scrollTop === 0`) never engage the indicator.
 */
export function pullState(
  dy: number,
  threshold: number,
  atTop: boolean,
): { progress: number; armed: boolean } {
  if (!atTop || dy <= 0) return { progress: 0, armed: false }
  const progress = Math.min(1, dy / threshold)
  return { progress, armed: dy >= threshold }
}

/**
 * Whether the element the pull gesture is attached to answers "am I at the
 * scroll top?" with its own `scrollTop`, or whether that question belongs to
 * the window.
 *
 * The pull surface is an inner content wrapper (it has to be: transforming
 * `document.documentElement` makes the root the containing block for every
 * `position: fixed` descendant, so the bottom nav, the scrim and the drawer
 * all shift during a pull). A wrapper that does not scroll itself reports
 * `scrollTop === 0` forever, which would arm a pull half-way down a long
 * list, so its own reading is only trusted when it really is a scroller.
 */
export function usesOwnScrollTop(
  overflowY: string,
  scrollHeight: number,
  clientHeight: number,
): boolean {
  const scrolls = overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay"
  return scrolls && scrollHeight > clientHeight
}

/**
 * Whether a pull may start at `clientX`, given the leading/trailing strips
 * `EdgeSwipeBack` reserves for itself (`EDGE_ZONE_PX`).
 *
 * `EdgeSwipeBack` listens on `document`, so a pointerdown on a pull surface
 * bubbles to it: without this the top-left 24px at `scrollY === 0` passed
 * both gestures' `startFilter`, giving two `setPointerCapture` calls, two
 * move handlers writing one `style.transform`, and two racing `springBack`s.
 * Excluding the strips here makes the two zones disjoint by construction —
 * the edge swipe owns `x <= EDGE_ZONE_PX` (and the mirrored trailing strip),
 * the pull owns everything strictly between them.
 */
export function pullStartAllowed(
  clientX: number,
  viewportWidth: number,
  edgeZonePx: number,
): boolean {
  return clientX > edgeZonePx && clientX < viewportWidth - edgeZonePx
}
