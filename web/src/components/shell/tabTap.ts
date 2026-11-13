/** Native frame: tapping the tab that is already active. Drilled in below the tab's root, the tap
 * pops back to the root (whatever the scroll position); at the root, the first tap scrolls to the
 * top and a tap already at the top does nothing. */
export function activeTabTap({ pathname, tabTo, scrollY }: { pathname: string; tabTo: string; scrollY: number }):
  | "scroll-top"
  | "pop-root"
  | "none" {
  const here = pathname.replace(/\/+$/, "")
  if (here !== tabTo.replace(/\/+$/, "")) return "pop-root"
  return scrollY > 0 ? "scroll-top" : "none"
}
