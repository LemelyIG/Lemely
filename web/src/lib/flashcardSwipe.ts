/*
 * Task 6 (B4b) · the pure decision behind `FlashcardReview`'s swipe gesture.
 * Kept dependency-free and out of the component so it is reachable from a
 * Node-only unit test (`vitest.config.ts`, D3.20) — same split as
 * `dragMath.ts`/`pullMath.ts`/`longPressMath.ts`.
 *
 * Before reveal, an upward or a rightward swipe both reveal the answer — no
 * swipe grades a card that hasn't been seen yet. After reveal, only the
 * horizontal axis matters: left is "again", right is "good". "hard" and
 * "easy" stay button/keyboard-only; a two-direction swipe has no honest way
 * to reach a four-way grade.
 */

export function flashcardSwipeAction({
  dx,
  dy,
  revealed,
}: {
  dx: number
  dy: number
  revealed: boolean
}): "reveal" | "again" | "good" | "none" {
  if (!revealed) {
    if (dy <= -60 || dx >= 60) return "reveal"
    return "none"
  }
  if (dx <= -80) return "again"
  if (dx >= 80) return "good"
  return "none"
}
