import { isInteractiveTagOrRole } from "./gestures/interactiveSelector"

/*
 * Task 6 (B4b) · the pure decision behind `QuizTaker`'s page-turn swipe.
 * Kept dependency-free and out of the component so it is reachable from a
 * Node-only unit test (`vitest.config.ts`, D3.20) — same split as
 * `dragMath.ts`/`pullMath.ts`/`longPressMath.ts`.
 *
 * Two independent reasons refuse the swipe: an interactive descendant
 * (`isInteractiveTagOrRole`, shared with every other gesture's interactive
 * check — see `gestures/interactiveSelector.ts`) owns its own tap already and
 * must never race a page-turn against it; and the last `SWIPE_LOCK_SECONDS`
 * of a timed test are the one moment a misfired swipe (losing the current
 * question's half-typed answer to an accidental page turn) costs the most.
 */

/** Seconds remaining in a timed test at which the page-turn swipe locks.
 * Exported so `QuizTaker.tsx`'s `useDragGesture` `enabled` gate and this
 * decision can never silently disagree. */
export const SWIPE_LOCK_SECONDS = 60

export function quizSwipeAllowed({
  remainingSeconds,
  targetTag,
  targetRole,
}: {
  remainingSeconds: number | null
  targetTag: string
  targetRole: string | null
}): boolean {
  if (isInteractiveTagOrRole(targetTag, targetRole)) return false
  if (remainingSeconds !== null && remainingSeconds <= SWIPE_LOCK_SECONDS) return false
  return true
}
