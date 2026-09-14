/*
 * Task 6 (B4b) · the pure decision behind `QuizTaker`'s page-turn swipe.
 * Kept dependency-free and out of the component so it is reachable from a
 * Node-only unit test (`vitest.config.ts`, D3.20) — same split as
 * `dragMath.ts`/`pullMath.ts`/`longPressMath.ts`.
 *
 * Two independent reasons refuse the swipe: an MCQ radio, a text input or a
 * button/link owns its own tap already and must never race a page-turn
 * against it; and the last 60 seconds of a timed test are the one moment a
 * misfired swipe (losing the current question's half-typed answer to an
 * accidental page turn) costs the most.
 */

const INTERACTIVE_TAGS = new Set(["TEXTAREA", "INPUT", "BUTTON", "A"])

export function quizSwipeAllowed({
  remainingSeconds,
  targetTag,
  targetRole,
}: {
  remainingSeconds: number | null
  targetTag: string
  targetRole: string | null
}): boolean {
  if (targetRole === "radio") return false
  if (INTERACTIVE_TAGS.has(targetTag.toUpperCase())) return false
  if (remainingSeconds !== null && remainingSeconds <= 60) return false
  return true
}
