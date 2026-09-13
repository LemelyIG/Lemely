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
 * the reader was scrolled to. `TAB_ROOTS` names those pathnames; this task
 * leaves the set empty (no `BottomNav` yet to populate it with), so every
 * route falls back to the ordinary per-entry key until Task 4 fills it in.
 */

export const TAB_ROOTS: ReadonlySet<string> = new Set()

export function scrollRestorationKey(
  location: { pathname: string; key: string },
  tabRoots: ReadonlySet<string> = TAB_ROOTS,
): string {
  return tabRoots.has(location.pathname) ? location.pathname : location.key
}
