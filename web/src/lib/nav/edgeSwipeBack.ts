/*
 * Packet B3 (Task 4) · the pure half of `EdgeSwipeBack` (`edge-swipe-back.tsx`
 * mounts it). Standalone-only — a browser tab already has the platform's own
 * edge-swipe/URL-bar back gesture, and installing a second one there would
 * fight it — and gated to a drag that both starts inside the 24px
 * inline-start edge zone and commits away from that edge, so a drag starting
 * mid-screen (dismissing a drawer, paging a quiz, B4's own gestures) is never
 * mistaken for this one.
 *
 * Consolidation pass · this used to re-run `dragMath.ts`'s `shouldCommitDrag`
 * on `away`/`dy` itself. It was a genuine second copy of the same gate:
 * `EdgeSwipeBack.tsx` wires `useDragGesture` with `axis: "x"` and no
 * `commitThreshold` override, so the hook's own `endDrag` already ran
 * `shouldCommitDrag(dx, dy, "x", 10)` — the identical default threshold and
 * axis — before it ever calls `onCommit`, which is the only place this
 * function is reached from. `away` is `dx * dir` and `dir` is always ±1, so
 * `Math.abs(away) === Math.abs(dx)`: the two calls could only ever agree,
 * and a future change to one `commitThreshold` with no matching change to
 * the other would have silently drifted them apart, same shape as the
 * threshold duplication fixed elsewhere in this pass. Every other pure
 * gesture decision in this codebase (`flashcardSwipeAction`,
 * `quizSwipeAllowed`) already trusts the hook's own commit gate rather than
 * re-deriving it, so this now does too — the distance/straightness check
 * lives once, in `dragMath.ts` (tested directly in `dragMath.test.ts`), and
 * this function only interprets the edge/direction meaning of a drag the
 * hook has already confirmed committed.
 */

export interface EdgeSwipeInput {
  /** The pointer's clientX at pointerdown. */
  startX: number
  dx: number
  dy: number
  viewportWidth: number
  standalone: boolean
  /** `1` in a left-to-right document (the edge is the left/start), `-1`
   * under `dir="rtl"` (the edge is the right/start). */
  dir: 1 | -1
}

/** How close to the inline-start edge a drag must start, in CSS pixels.
 * Exported so `EdgeSwipeBack` can gate `useDragGesture`'s `startFilter` on
 * the same number rather than a second, driftable copy of it. */
export const EDGE_ZONE_PX = 24

export function edgeSwipeDecision({
  startX,
  dx,
  viewportWidth,
  standalone,
  dir,
}: EdgeSwipeInput): "back" | "none" {
  if (!standalone) return "none"

  const onEdge = dir === 1 ? startX <= EDGE_ZONE_PX : startX >= viewportWidth - EDGE_ZONE_PX
  if (!onEdge) return "none"

  // Signed so "away from the edge" is always positive, regardless of which
  // edge this is — a drag back toward the edge (or past it, off-screen) is
  // not a back gesture.
  const away = dx * dir
  if (away <= 0) return "none"

  return "back"
}
