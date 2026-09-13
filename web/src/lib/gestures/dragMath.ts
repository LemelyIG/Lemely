/*
 * Packet B3 (Task 4) · the pure decision `useDragGesture` (and every gesture
 * built on it) reduces a drag to: has this committed, and how far along is
 * it. Kept dependency-free and out of the hook itself so it is reachable from
 * a Node-only unit test (`vitest.config.ts` runs with no jsdom, D3.20) —
 * `useDragGesture.ts` calls these, it does not reimplement them.
 */

export type DragAxis = "x" | "y"

/**
 * Has a drag travelled far enough, and straight enough, along `axis` to
 * count as a committed gesture rather than an accidental wobble or a scroll
 * on the other axis? `threshold` is in the same units as `dx`/`dy` (CSS
 * pixels from the pointer's start position). The "straight enough" half —
 * the dominant axis must outrun the other by more than 2x — is what lets a
 * drawer's horizontal drag-dismiss coexist with the list inside it
 * scrolling vertically: a mostly-vertical drag never commits on `axis: "x"`.
 */
export function shouldCommitDrag(dx: number, dy: number, axis: DragAxis, threshold = 10): boolean {
  const along = axis === "x" ? dx : dy
  const across = axis === "x" ? dy : dx
  return Math.abs(along) > threshold && Math.abs(along) > 2 * Math.abs(across)
}

/** `delta` as a 0..1 fraction of `distance`, magnitude only (direction is the
 * caller's concern) and clamped at both ends — a non-positive `distance` is
 * never divided into, so it reads as "no progress" rather than `Infinity`. */
export function dragProgress(delta: number, distance: number): number {
  if (distance <= 0) return 0
  const ratio = Math.abs(delta) / distance
  return Math.min(1, Math.max(0, ratio))
}
