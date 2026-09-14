/*
 * Task 5 (B4a) · the pure decision `useLongPress` reduces a held pointer to
 * on every pointermove: keep waiting, or cancel because it moved too far.
 * Kept dependency-free and out of the hook itself so it is reachable from a
 * Node-only unit test (`vitest.config.ts` runs with no jsdom, D3.20) — same
 * split as `dragMath.ts`/`pullMath.ts`.
 *
 * Consolidation pass · this used to also return `"fire"` (from `elapsedMs >=
 * holdMs`) and take a `startedOnInteractive` flag, both dead: the hold
 * actually fires from `useLongPress.ts`'s own `setTimeout`, unconditionally,
 * at `holdMs` — nothing ever read this function's `"fire"` outcome, so a
 * `pointermove` landing exactly on the deadline and one landing well past it
 * were indistinguishable to the one caller that mattered. And
 * `startedOnInteractive` was hardcoded `false` at the only call site
 * (`onPointerMove`): the real check is `shouldStartLongPress` at
 * `onPointerDown`, and a press that fails it never reaches `onPointerMove`'s
 * state at all — so the flag here could never actually be `true`. Both are
 * gone; `shouldStartLongPress` (below) is the one real interactive check.
 */

export interface LongPressDecisionInput {
  movedPx: number
  moveTolerance: number
}

export function longPressDecision(input: LongPressDecisionInput): "wait" | "cancel" {
  return input.movedPx > input.moveTolerance ? "cancel" : "wait"
}

/**
 * Whether a `pointerdown` should start the hold timer at all.
 *
 * Touch and pen presses report `button: 0`, as does a primary mouse press;
 * anything above that is a secondary or middle mouse button, which belongs to
 * the browser (its own context menu, its own paste) and never to us.
 */
export function shouldStartLongPress(input: {
  button: number
  startedOnInteractive: boolean
}): boolean {
  return input.button === 0 && !input.startedOnInteractive
}

/**
 * Whether to `preventDefault()` a `contextmenu` event.
 *
 * Only for a touch/pen hold, where our own menu is about to open in the
 * native one's place. A mouse right-click gets the browser's menu: we offer
 * nothing to replace it with, and suppressing it left the user with nothing
 * at all.
 */
export function shouldSuppressContextMenu(pointerType: string, pressActive: boolean): boolean {
  return pressActive && pointerType !== "mouse"
}
