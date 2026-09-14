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
