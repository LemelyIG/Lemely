/*
 * Task 5 (B4a) · the pure decision `useLongPress` reduces a held pointer to
 * on every pointermove (and, implicitly, its `holdMs` timer): keep waiting,
 * fire, or cancel. Kept dependency-free and out of the hook itself so it is
 * reachable from a Node-only unit test (`vitest.config.ts` runs with no
 * jsdom, D3.20) — same split as `dragMath.ts`/`pullMath.ts`.
 */

export interface LongPressDecisionInput {
  elapsedMs: number
  movedPx: number
  holdMs: number
  moveTolerance: number
  /** The press started on a descendant (`button`, `a`, a form control, an
   * ARIA radio/checkbox) that already owns click/tap — long-press defers to
   * it entirely rather than racing its own gesture against native behaviour. */
  startedOnInteractive: boolean
}

export function longPressDecision(input: LongPressDecisionInput): "fire" | "wait" | "cancel" {
  const { elapsedMs, movedPx, holdMs, moveTolerance, startedOnInteractive } = input
  if (startedOnInteractive) return "cancel"
  if (movedPx > moveTolerance) return "cancel"
  if (elapsedMs >= holdMs) return "fire"
  return "wait"
}
