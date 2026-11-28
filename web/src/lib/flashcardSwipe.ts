/*
 * Task 6 (B4b) · the pure decision behind `FlashcardReview`'s swipe gesture.
 * Kept dependency-free and out of the component so it is reachable from a
 * Node-only unit test (`vitest.config.ts`, D3.20) — same split as
 * `dragMath.ts`/`pullMath.ts`/`longPressMath.ts`.
 *
 * Before reveal, a rightward swipe reveals the answer — no swipe grades a
 * card that hasn't been seen yet. After reveal, left is "again", right is
 * "good". "hard" and "easy" stay button/keyboard-only; a two-direction swipe
 * has no honest way to reach a four-way grade.
 *
 * Consolidation pass · this used to also take a `dy` and reveal on `dy <=
 * -60`, which `FlashcardReview.tsx` claimed was "reachable via a diagonal
 * drag". It genuinely could fire, but only via a drag whose horizontal
 * component *dominates and is negative* — a predominantly leftward drag
 * tilted upward enough — which is the exact direction "no leftward swipe
 * reveals" says must never fire. `useDragGesture`'s `shouldCommitDrag` gate
 * (`axis: "x"`) requires `|dx| > 2|dy|`, so a genuine vertical swipe (`dx:
 * 0`) can never commit at all; the only reachable path through the removed
 * branch was the buggy leftward-tilted one. Dropped rather than fixed into a
 * real second axis — `commitThreshold`/`onCommit` here are already a single
 * horizontal gesture, and a vertical reveal shortcut is not worth growing
 * this into a two-axis system for.
 */

/** Horizontal distance, in CSS pixels, a swipe must commit past to reveal
 * the answer. Exported so `FlashcardReview.tsx`'s `useDragGesture`
 * `commitThreshold` and this decision can never silently disagree. */
export const REVEAL_SWIPE_THRESHOLD = 60

/** Horizontal distance, in CSS pixels, a swipe must commit past (either
 * direction) to grade a revealed card. Same reasoning as `REVEAL_SWIPE_THRESHOLD`. */
export const GRADE_SWIPE_THRESHOLD = 80

export function flashcardSwipeAction({
  dx,
  revealed,
}: {
  dx: number
  revealed: boolean
}): "reveal" | "again" | "good" | "none" {
  if (!revealed) {
    return dx >= REVEAL_SWIPE_THRESHOLD ? "reveal" : "none"
  }
  if (dx <= -GRADE_SWIPE_THRESHOLD) return "again"
  if (dx >= GRADE_SWIPE_THRESHOLD) return "good"
  return "none"
}

export interface SwipeVisual {
  stamp: "again" | "good" | null
  /** 0..1, reaches 1 at the grade threshold. */
  opacity: number
  rotateDeg: number
  /** Past the threshold: releasing now grades. */
  armed: boolean
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** What the card shows mid-drag. Pure, so the stamp maths are unit-tested. Reduced motion
 * keeps the stamp (it carries meaning) but never tilts the card. */
export function swipeVisual(dx: number, revealed: boolean, reduced: boolean): SwipeVisual {
  if (!revealed) {
    return { stamp: null, opacity: 0, rotateDeg: reduced ? 0 : clamp(dx * 0.05, -6, 6), armed: false }
  }
  return {
    stamp: dx > 0 ? "good" : dx < 0 ? "again" : null,
    opacity: clamp(Math.abs(dx) / GRADE_SWIPE_THRESHOLD, 0, 1),
    rotateDeg: reduced ? 0 : clamp(dx * 0.08, -12, 12),
    armed: Math.abs(dx) >= GRADE_SWIPE_THRESHOLD,
  }
}
