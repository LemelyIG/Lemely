/*
 * Packet B2a · the `getKey` react-router's `<ScrollRestoration>` (mounted
 * once in `RootOutlet`) uses to decide what identifies "the same place" for
 * restoring scroll.
 *
 * The default behaviour keys by `location.key` — a fresh key per history
 * entry, so navigating away and back (even to the same URL) starts scrolled
 * to the top, which is right for drilling into a subject and back out. A
 * bottom-tab root is different: switching from Overview to Classes and back
 * to Overview is the same screen, and Task 4 (B3) wants it to remember where
 * the reader was scrolled to. `TAB_ROOTS` names those pathnames.
 *
 * Packet B3 (Task 4): filled with the student and teacher `BottomNav`/
 * `SidebarNav` roots — the screens a reader actually switches between with a
 * tab tap rather than drilling into. `/student/correct` is a tab (it is one
 * of the five `BottomNav` destinations) even though it has no bottom CTA of
 * its own; admin has no `BottomNav` (desktop-first, see `portals/admin/
 * index.tsx`) and so contributes no roots here.
 *
 * Consolidation pass · `lib/nav/tabMemory.ts`'s `useTabState` used to import
 * this same set for a parallel per-tab UI-state memory (a filter, an
 * expanded section). It had zero callers — none of Overview/Classes/Profile/
 * Notifications hold local UI state that would benefit from surviving a tab
 * switch — so it was deleted rather than kept as speculative dead code; this
 * `TAB_ROOTS` set now backs scroll restoration only.
 */

export const TAB_ROOTS: ReadonlySet<string> = new Set([
  "/student",
  "/student/correct",
  "/student/classes",
  "/student/profile",
  "/teacher",
  "/teacher/grading",
  "/teacher/review",
  "/teacher/classes",
])

export function scrollRestorationKey(
  location: { pathname: string; key: string },
  tabRoots: ReadonlySet<string> = TAB_ROOTS,
): string {
  return tabRoots.has(location.pathname) ? location.pathname : location.key
}

/**
 * Route-backed overlays (the teacher Settings dialog): paths at and under
 * these render as a dialog over the page the reader was on, not as a page.
 */
export const OVERLAY_BASES: readonly string[] = ["/teacher/settings"]

function inOverlay(pathname: string, bases: readonly string[]): boolean {
  const trimmed = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
  return bases.some((base) => trimmed === base || trimmed.startsWith(`${base}/`))
}

/**
 * A `getKey` that also knows about route-backed overlays.
 *
 * Opening an overlay is a navigation, and react-router resets scroll to the
 * top on a navigation it has no saved position for. Under a dialog that
 * reset moved the page underneath to the top (the dialog's scroll lock then
 * pinned it there, and closing restored the top). An overlay location is
 * therefore keyed as the page it opened over (the last non-overlay key this
 * keyer produced): the "restore" on opening is that page's own position, a
 * no-op, so the page stays put. With no page seen yet (a deep link or a
 * refresh on the overlay), it keys normally.
 */
export function createScrollKeyer(
  tabRoots: ReadonlySet<string> = TAB_ROOTS,
  overlayBases: readonly string[] = OVERLAY_BASES,
): (location: { pathname: string; key: string }) => string {
  let lastPageKey: string | null = null
  return (location) => {
    if (inOverlay(location.pathname, overlayBases)) {
      return lastPageKey ?? scrollRestorationKey(location, tabRoots)
    }
    lastPageKey = scrollRestorationKey(location, tabRoots)
    return lastPageKey
  }
}
