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
