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
 *
 * Issue #246/#247, opus review (Minor-5): `role="link"`/`"switch"`/`"tab"`/
 * `"menuitem"`, `summary`, `[contenteditable]`, and
 * `[tabindex]:not([tabindex="-1"])` were all missing — latent, not live, at
 * the time this was found (every control on the three pull-to-refresh
 * screens is a plain `Button`/`Link`, so nothing on them exercised the gap),
 * but the next screen with a custom tab strip or an editable region would
 * have hit the same click-swallowing bug this file exists to prevent.
 * `FOCUSABLE_SELECTOR` (`modal.tsx`) already carried the wider tag/attribute
 * list this was meant to stop drifting from; folded the gap back in here.
 *
 * `[contenteditable]` and `[tabindex]:not([tabindex="-1"])` are appended to
 * `GESTURE_INTERACTIVE_SELECTOR` directly rather than through
 * `INTERACTIVE_TAGS`/`INTERACTIVE_ROLES`: neither is a tag name or a role
 * value, so `isInteractiveTagOrRole`'s `(tag, role)` pair cannot express
 * either without a signature change no current caller asked for. Every
 * present call site but one reaches this file through `.closest()` on a live
 * node — `useLongPress.ts`, `FlashcardReview.tsx`, `nav-drawer.tsx`,
 * `edge-swipe-back.tsx`, `usePullToRefresh.ts` — so all five gain the two new
 * attribute checks for free. The quiz swipe does not. `QuizTaker.tsx` runs
 * `.closest(GESTURE_INTERACTIVE_SELECTOR)`, but then passes the match's tag
 * and role to `quizSwipeAllowed`, which decides through
 * `isInteractiveTagOrRole`. A match found only by `[contenteditable]` or
 * `[tabindex]` is usually a `DIV` with no role, which that check reads as
 * non-interactive, so the quiz swipe still starts on it.
 */

const INTERACTIVE_TAGS = new Set(["BUTTON", "A", "INPUT", "TEXTAREA", "SELECT", "LABEL", "SUMMARY"])
const INTERACTIVE_ROLES = new Set(["radio", "checkbox", "button", "link", "switch", "tab", "menuitem"])

/** Attribute selectors with no tag/role equivalent — see the module comment
 * above for why these two live outside `INTERACTIVE_TAGS`/`INTERACTIVE_ROLES`. */
const INTERACTIVE_ATTRIBUTE_SELECTORS = ["[contenteditable]", '[tabindex]:not([tabindex="-1"])']

export const GESTURE_INTERACTIVE_SELECTOR = [
  ...[...INTERACTIVE_TAGS].map((tag) => tag.toLowerCase()),
  ...[...INTERACTIVE_ROLES].map((role) => `[role="${role}"]`),
  ...INTERACTIVE_ATTRIBUTE_SELECTORS,
].join(", ")

/** DOM-free equivalent of `element.closest(GESTURE_INTERACTIVE_SELECTOR) !== null`,
 * for a caller that already has the tag/role pair rather than a live node.
 * Cannot see `[contenteditable]`/`[tabindex]` — see the module comment. */
export function isInteractiveTagOrRole(tag: string, role: string | null): boolean {
  return INTERACTIVE_TAGS.has(tag.toUpperCase()) || (role !== null && INTERACTIVE_ROLES.has(role))
}
