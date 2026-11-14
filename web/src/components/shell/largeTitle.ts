/** Native frame Task 4: a section page (trail of 0 or 1 crumbs) is a tab root
 * with a large title; a drilled-in page is a detail with the compact bar. */
export function titleLevelFor(trail: readonly unknown[], tabRoot = false): "root" | "detail" {
  return tabRoot || trail.length <= 1 ? "root" : "detail"
}

/** A bottom-tab destination is a root whatever its trail says: the teacher trail for
 * Grading, Review and Classes is [Overview, Section] (two crumbs, for the desktop breadcrumb),
 * and a tab you tapped into has nothing to go back to. */
export function isTabRoot(pathname: string, tabPaths: readonly string[]): boolean {
  const path = pathname.replace(/\/+$/, "") || "/"
  return tabPaths.includes(path)
}

/** The large title sits directly under the sticky bar, so its bottom reaches
 * the bar's bottom exactly when the page has scrolled by its own height. */
export function largeTitleCollapsed(scrollY: number, titleHeight: number): boolean {
  return titleHeight > 0 && scrollY >= titleHeight
}
