/**
 * Task 11 (B6c) — prefetch a lazy route chunk on the first sign of intent
 * (pointer hover, touch, or keyboard focus) rather than waiting for the
 * click that actually navigates.
 *
 * `portals/student/index.tsx` calls this once, at module scope, for
 * `loadCorrectPaper` — the same loader passed to `React.lazy` — and spreads
 * the three handlers it returns across every call site that can signal
 * intent to visit `/student/correct` (the Header CTA, `BottomActionBar`,
 * the BottomNav "Correct" tab). One call, one fire-once gate: hovering the
 * CTA and then focusing the tab must still only import the chunk once, not
 * once per handler.
 */
export interface PrefetchIntentHandlers {
  onPointerEnter: () => void
  onTouchStart: () => void
  onFocus: () => void
}

export function prefetchOnIntent(load: () => Promise<unknown>): PrefetchIntentHandlers {
  let fired = false
  const trigger = () => {
    if (fired) return
    fired = true
    void load()
  }
  return { onPointerEnter: trigger, onTouchStart: trigger, onFocus: trigger }
}
