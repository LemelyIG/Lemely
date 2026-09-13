import { shouldCommitDrag } from "@/lib/gestures/dragMath"

/*
 * Packet B3 (Task 4) · the pure half of `EdgeSwipeBack` (`edge-swipe-back.tsx`
 * mounts it). Standalone-only — a browser tab already has the platform's own
 * edge-swipe/URL-bar back gesture, and installing a second one there would
 * fight it — and gated to a drag that both starts inside the 24px
 * inline-start edge zone and commits away from that edge, so a drag starting
 * mid-screen (dismissing a drawer, paging a quiz, B4's own gestures) is never
 * mistaken for this one.
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
  dy,
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

  if (!shouldCommitDrag(away, dy, "x")) return "none"

  return "back"
}
