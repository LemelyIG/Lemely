import { matchPath } from "react-router-dom"

/*
 * Pure student nav rules for the mock tab bar and rail (student-r2/h6.js TAB6/DRAIL6).
 */

/** The Practice tab's root. L4's hub replaces the interim SubjectEntry at this path. */
export const STUDENT_PRACTICE_TO = "/student/practice"

/** The Plan tab's root. L9 replaces the interim SubjectEntry at this path. */
export const STUDENT_PLAN_TO = "/student/plan"

/** Practice and flashcards both light the Practice tab and rail item. */
export function isPracticeSection(path: string): boolean {
  return /^\/student\/(practice|flashcards)(\/|$)/.test(path)
}

/** The study plan, its subject weeks and its sessions light the Plan tab and rail item. */
export function isPlanSection(path: string): boolean {
  return /^\/student\/plan(\/|$)/.test(path)
}

/**
 * Practice and Plan only redirect to a subject page, so the student is never "at" their tab path. Interim, until
 * L4 and L9 land real hubs: the subject-level page (`/student/practice/:code`, `/student/plan/:code`, one segment)
 * counts as the tab's root. Flashcards also light Practice but are deliberately NOT roots: they are a drill-in
 * from a subject, with a back chevron, and Practice's re-tap pops out of them. Deeper pages (practice sets,
 * plan sessions) are details. L4: `/student/practice/papers` is the Past papers screen, a drill-in from the hub,
 * so it is not a root and keeps its back path.
 */
export function isStudentSubjectRoot(path: string): boolean {
  return /^\/student\/(practice(?!\/papers\/?$)|plan)\/[^/]+\/?$/.test(path)
}

/** The old sidebar rows minus Overview (Home is a tab): they become the sidebar's More group. */
export function studentOverflowItems<T extends { to?: string }>(items: readonly T[]): T[] {
  return items.filter((item) => item.to !== "/student")
}

/**
 * While Settings is a dialog route the URL is the dialog's, so a row's own NavLink matches nothing. The row for the
 * page underneath (Home on a fresh load, where the shell falls back to /student) is lit here instead.
 * Returns undefined when no dialog is open, leaving the row to its own match.
 */
export function underDialogActive(item: { to: string; end?: boolean }, pagePath: string, pathname: string): true | undefined {
  if (pagePath === pathname) return undefined
  return matchPath({ path: item.to, end: item.end ?? false }, pagePath) ? true : undefined
}
