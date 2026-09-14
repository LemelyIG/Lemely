/*
 * Consolidation pass · four gesture call sites (`useLongPress.ts`,
 * `QuizTaker.tsx`'s page-turn swipe, `FlashcardReview.tsx`'s card swipe, and
 * `quizSwipe.ts`'s pure decision) each kept their own ad-hoc list of "which
 * elements already own their own click/tap and must never race a gesture
 * against it". The four had drifted from each other — none of them excluded
 * `label` or `[role="button"]`. This is the one place that list is written
 * down; every call site imports from here instead of restating it.
 *
 * Two shapes are exported because two different call shapes need it: a live
 * DOM node can ask `.closest(GESTURE_INTERACTIVE_SELECTOR)`, but `quizSwipe.ts`'s
 * decision function is kept dependency-free so it is reachable from a
 * Node-only unit test (no jsdom, D3.20) — it only ever sees an
 * already-extracted tag/role pair, never a live `Element`, so it needs the
 * same list expressed as a predicate instead of a CSS selector.
 */

const INTERACTIVE_TAGS = new Set(["BUTTON", "A", "INPUT", "TEXTAREA", "SELECT", "LABEL"])
const INTERACTIVE_ROLES = new Set(["radio", "checkbox", "button"])

export const GESTURE_INTERACTIVE_SELECTOR = [
  ...[...INTERACTIVE_TAGS].map((tag) => tag.toLowerCase()),
  ...[...INTERACTIVE_ROLES].map((role) => `[role="${role}"]`),
].join(", ")

/** DOM-free equivalent of `element.closest(GESTURE_INTERACTIVE_SELECTOR) !== null`,
 * for a caller that already has the tag/role pair rather than a live node. */
export function isInteractiveTagOrRole(tag: string, role: string | null): boolean {
  return INTERACTIVE_TAGS.has(tag.toUpperCase()) || (role !== null && INTERACTIVE_ROLES.has(role))
}
