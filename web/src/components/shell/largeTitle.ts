/** Native frame Task 4: a section page (trail of 0 or 1 crumbs) is a tab root
 * with a large title; a drilled-in page is a detail with the compact bar. */
export function titleLevelFor(trail: readonly unknown[]): "root" | "detail" {
  return trail.length > 1 ? "detail" : "root"
}

/** The large title sits directly under the sticky bar, so its bottom reaches
 * the bar's bottom exactly when the page has scrolled by its own height. */
export function largeTitleCollapsed(scrollY: number, titleHeight: number): boolean {
  return titleHeight > 0 && scrollY >= titleHeight
}
