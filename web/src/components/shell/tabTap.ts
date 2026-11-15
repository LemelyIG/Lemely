/** Tapping the tab that is already active (wherever the tab bar shows). Drilled in below the tab's root, the tap
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

/** A plain primary-button click. A modified or non-primary click on a tab keeps the browser's own behaviour (new tab, new window). */
export function isPlainPrimaryClick(event: { button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean }): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey
}
