/** Native frame Task 5: the first tap on the active tab scrolls to the top;
 * once at the top, the next tap pops a drilled-in page back to the tab root. */
export function activeTabTap({ pathname, tabTo, scrollY }: { pathname: string; tabTo: string; scrollY: number }):
  | "scroll-top"
  | "pop-root"
  | "none" {
  if (scrollY > 0) return "scroll-top"
  const here = pathname.replace(/\/+$/, "")
  return here === tabTo.replace(/\/+$/, "") ? "none" : "pop-root"
}
