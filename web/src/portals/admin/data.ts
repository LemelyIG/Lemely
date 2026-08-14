/*
 * Admin portal config — navigation and crumb trails for the two admin lanes.
 * Not mock data: nothing in this file is a number, and every screen it names
 * reads a real endpoint (P4.7, UI spec K-01…K-04 and X-01…X-03).
 *
 * ── Why two lanes and not one portal ───────────────────────────────────────
 *
 * `school_admin` and `platform_admin` were bundled together in `routes.tsx`'s
 * `TEACHER_ROLES` for the whole build, and the bundle hid that they are not
 * alike in any way that matters:
 *
 * * A **school admin** genuinely holds the teacher API's data. Every staff
 *   router scopes them to the schools they hold a `school_admin` membership
 *   for (`class_repo.list_classes`, `teacher._visible_students`,
 *   `announcement_repo`), so the teacher portal's screens really do show them
 *   their school. They keep that access; `/school` is their *home*, not their
 *   cage.
 * * A **platform admin** holds none of it, deliberately. Every one of those
 *   same routers returns empty for them — "no super-role bypass", D1.6/D1.10,
 *   stated in `class_repo.py`, `review.py`, `teacher.py` and `at_risk_repo.py`
 *   alike. So the teacher portal could only ever have shown them a console
 *   where every panel was correctly, permanently blank. They are removed from
 *   `TEACHER_ROLES` and live at `/platform`.
 *
 * The two lanes share one shell implementation and differ only in this file.
 */

export interface AdminNavItem {
  to: string
  label: string
  /** Which phosphor icon renders in the sidebar. */
  icon: "dashboard" | "seats" | "teachers" | "classes" | "console" | "activations" | "pipeline"
  /** Index route match (the lane's dashboard lives at its root). */
  end?: boolean
}

/** K-01…K-04, in the order the work happens: look, then provision, then staff. */
export const schoolNavItems: AdminNavItem[] = [
  { to: "/school", label: "Dashboard", icon: "dashboard", end: true },
  { to: "/school/seats", label: "Seats and students", icon: "seats" },
  { to: "/school/teachers", label: "Teachers", icon: "teachers" },
  { to: "/school/classes", label: "Classes", icon: "classes" },
]

/** X-01…X-03. The queue sits second because it is the only one with work in it. */
export const platformNavItems: AdminNavItem[] = [
  { to: "/platform", label: "Console", icon: "console", end: true },
  { to: "/platform/activations", label: "Activations", icon: "activations" },
  { to: "/platform/pipeline", label: "Pipeline and corpus", icon: "pipeline" },
]

export interface TrailCrumb {
  label: string
  to?: string
}

/**
 * The breadcrumb trail for an admin path.
 *
 * Both lanes are flat — every screen is one hop from its dashboard — so this is
 * a lookup rather than the pattern-matching ladder the teacher portal needs.
 * Labels come from the nav lists so the trail and the sidebar cannot disagree
 * about what a section is called.
 *
 * An unmatched path returns the root alone, which the layout renders as no
 * trail at all. That is the honest outcome: no claim about where you are beats
 * a confident wrong one.
 */
export function resolveAdminTrail(pathname: string, lane: AdminLane): TrailCrumb[] {
  const items = lane === "school" ? schoolNavItems : platformNavItems
  const rootPath = lane === "school" ? "/school" : "/platform"
  const rootLabel = items[0].label
  const path = pathname.replace(/\/+$/, "") || rootPath

  if (path === rootPath) return [{ label: rootLabel }]

  const section = items.find((item) => item.to === path)
  if (section) return [{ label: rootLabel, to: rootPath }, { label: section.label }]

  return [{ label: rootLabel, to: rootPath }]
}

/** Which admin lane a shell is rendering. */
export type AdminLane = "school" | "platform"

/**
 * A date an administrator can read without guessing the convention.
 *
 * The first draft used a bare `toLocaleDateString()`, which rendered
 * `8/11/2026` on the capture machine. That is 11 August to the browser's
 * default locale and 8 November to most of the people this product is built
 * for, and nothing on the screen says which — on a column headed "Last marked",
 * a three-month error is invisible. Naming the month removes the ambiguity
 * entirely, and the day/short-month/year shape is what the student and teacher
 * screens already use.
 *
 * `undefined` locale on purpose: the *order* of the parts should still follow
 * the reader's own conventions. It is the numeric month that was unsafe, not
 * the ordering.
 */
export function formatAdminDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}
