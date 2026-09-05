/*
 * Teacher portal config — NOT mock data. What remains here after P3.8 chunk c
 * is real, hand-authored navigation/UI config that has nothing to do with the
 * Claude Design mock's stubbed numbers: `navItems` (the sidebar route list,
 * consumed by `portals/teacher/index.tsx`) and the `StatCard` interface
 * (consumed by `portals/teacher/components/StatCard.tsx`). Both are imported
 * by real screens today, not scaffolding for one this build hasn't reached.
 *
 * Every mock-data export that used to live here is gone. P3.7 chunk B moved
 * Overview/Classes onto real data and deleted the arrays only they consumed
 * (`recentClasses`, `classStats`/`mastery`/`distribution`/`bubble`/
 * `students`). Chunk c (T-09) deletes the last of them — `Difficulty`,
 * `difficulties`, `difficultyNote`, `predictedAvg`, `defaultTopics`,
 * `QuestionPool`, `pools`, `defaultPools`, `PreviewQuestion`, `preview`,
 * `estMinutes` — which `Quizzes.tsx` alone rendered before it was rebuilt
 * against `GET /teacher/quizzes` and the rest of the real quiz-builder API
 * (`useTeacherApi.ts`). **Correction to `BUILD/STATE.md`'s P3.8 plan**: it
 * says "data.ts should be gone by the end of chunk c" — that predates
 * anyone checking `navItems`/`StatCard`'s other two importers; deleting the
 * file now would break both. See the phase report.
 */

/* ── Sidebar ─────────────────────────────────────────────────────────────── */

export interface NavItem {
  to: string
  label: string
  /** Which phosphor icon renders in the sidebar. */
  icon:
    | "overview"
    | "grading"
    | "review"
    | "classes"
    | "atRisk"
    | "schemes"
    | "quizzes"
    | "announcements"
    | "settings"
  /** Index route match (Overview lives at /teacher). */
  end?: boolean
}

/*
 * P3.1 (DECISION D1.2, defaulted-approved on timeout): "Review" is new here.
 *
 * The confidence-review queue is the product's stated positioning — marking
 * that hands back what it is unsure about instead of guessing — and it is the
 * only mechanism that makes the accuracy numbers defensible. It nevertheless
 * had no persistent navigation of any kind. `/teacher/review` was reachable
 * only through conditional CTAs on two other screens, which means it was
 * reachable only when those screens decided there was something to review. A
 * teacher could not go and check whether the queue was empty; they could only
 * be told it was not.
 *
 * It sits directly after Grading because that is the order the work happens
 * in: mark the papers, then look at what marking flagged.
 */
export const navItems: NavItem[] = [
  { to: "/teacher", label: "Overview", icon: "overview", end: true },
  { to: "/teacher/grading", label: "Grading", icon: "grading" },
  { to: "/teacher/review", label: "Review", icon: "review" },
  // `end: true`: without it this row also matched `/teacher/classes/:id`, so
  // opening a class from "Your classes" below highlighted both rows at once.
  { to: "/teacher/classes", label: "Classes", icon: "classes", end: true },
  { to: "/teacher/at-risk", label: "At-risk students", icon: "atRisk" },
  { to: "/teacher/schemes", label: "Mark schemes", icon: "schemes" },
  { to: "/teacher/quizzes", label: "AI quizzes", icon: "quizzes" },
  { to: "/teacher/announcements", label: "Announcements", icon: "announcements" },
  // Settings moves into the primary nav from the footer's plain link (P5.9
  // chunk D's placement is superseded here): a route under /teacher with a
  // real active state belongs beside the rest of this teacher's sections
  // rather than set apart as an account-level afterthought.
  { to: "/teacher/settings", label: "Settings", icon: "settings" },
]

/* ── Breadcrumb trail (P3.1 / DECISION D1.5) ─────────────────────────────── */

export interface TrailCrumb {
  label: string
  /** Absent on the crumb for the current page: you do not link to where you are. */
  to?: string
}

/**
 * Resolve the breadcrumb trail for a teacher pathname.
 *
 * A pure function in the data module rather than logic inside the layout
 * component, for the reason the student portal's `resolveCrumb` records the
 * hard way: while it lived inside a React module no test could reach it, and a
 * route whose crumb silently fell through to a wrong-but-plausible default
 * ("Home") tripped no typecheck, no axe rule and no threshold. The teacher
 * trail has more branches than that one did, so it gets unit tests instead.
 *
 * Two rules the labels follow:
 *
 * 1. **No interpolated ids.** `/teacher/students/:studentId` resolves to "This
 *    student", not to the UUID and not to a fetched display name. A UUID is
 *    noise, and resolving the name would make navigation chrome depend on a
 *    request that can be pending or fail — the trail has to be right on first
 *    paint or it is not a wayfinding aid. The crumb's job here is the link
 *    *back* to the roster, which is correct without knowing the name.
 * 2. **Every intermediate crumb links somewhere real.** A crumb that renders
 *    as inert text is worse than no crumb, because it looks like a way back
 *    and is not. Where a level has no listing route of its own it is left out
 *    of the trail rather than rendered dead.
 */
export function resolveTrail(pathname: string): TrailCrumb[] {
  const root: TrailCrumb = { label: "Overview", to: "/teacher" }

  // Normalised once so a trailing slash cannot miss every arm below.
  const path = pathname.replace(/\/+$/, "") || "/teacher"

  if (path === "/teacher") return [{ label: "Overview" }]

  const find = (to: string) => navItems.find((item) => item.to === to)?.label

  // Flat sections: one hop from Overview, label taken from the nav list so the
  // trail and the sidebar can never disagree about what a section is called.
  const flat = find(path)
  if (flat) return [root, { label: flat }]

  const reviewItem = path.match(/^\/teacher\/review\/[^/]+$/)
  if (reviewItem) {
    return [root, { label: "Review", to: "/teacher/review" }, { label: "This item" }]
  }

  if (path === "/teacher/settings/devices") {
    return [
      root,
      { label: "Settings", to: "/teacher/settings" },
      { label: "Account and devices" },
    ]
  }

  if (path === "/teacher/settings/notifications") {
    return [root, { label: "Settings", to: "/teacher/settings" }, { label: "Notifications" }]
  }

  const classAnalytics = path.match(/^\/teacher\/classes\/([^/]+)\/analytics$/)
  if (classAnalytics) {
    return [
      root,
      { label: "Classes", to: "/teacher/classes" },
      { label: "This class", to: `/teacher/classes/${classAnalytics[1]}` },
      { label: "Analytics" },
    ]
  }

  const classDetail = path.match(/^\/teacher\/classes\/[^/]+$/)
  if (classDetail) {
    return [root, { label: "Classes", to: "/teacher/classes" }, { label: "This class" }]
  }

  // Reached by drilling in from a class roster or the at-risk list, and until
  // P3.1 it rendered no route back to either. There is no students *listing*
  // route to point the middle crumb at, so the trail is two levels, not a
  // three-level one with a dead middle.
  const studentDetail = path.match(/^\/teacher\/students\/[^/]+$/)
  if (studentDetail) return [root, { label: "This student" }]

  const quizResults = path.match(
    /^\/teacher\/quizzes\/([^/]+)\/assignments\/[^/]+\/results$/,
  )
  if (quizResults) {
    return [
      root,
      { label: "AI quizzes", to: "/teacher/quizzes" },
      { label: "This quiz", to: `/teacher/quizzes/${quizResults[1]}` },
      { label: "Results" },
    ]
  }

  const quizBuilder = path.match(/^\/teacher\/quizzes\/[^/]+$/)
  if (quizBuilder) {
    return [root, { label: "AI quizzes", to: "/teacher/quizzes" }, { label: "This quiz" }]
  }

  // An unmatched teacher path is a route this function has not been taught.
  // Returning the root alone renders no trail at all (the layout hides a
  // one-crumb trail), which is the honest outcome: no claim about where you
  // are beats a confident wrong one.
  return [root]
}

/**
 * Whether the "Classes" nav row should read as active for the given pathname.
 *
 * `navItems`'s own `end: true` on this row means NavLink's default `isActive`
 * fires only on the exact `/teacher/classes` path, deliberately, so opening a
 * class from "Your classes" below highlights that class's own row instead of
 * this one. But "Your classes" (`ClassesNavSection`) is capped at 5, so a
 * class beyond the cap has no row of its own to highlight — and with `end:
 * true` this row does not pick it up either, leaving no active row anywhere
 * in the sidebar while a class screen is open. This function is that
 * fallback: true on the exact classes path, and also true on a class (or its
 * `/analytics` child) that is not among the ids currently rendered as rows,
 * so "Classes" itself carries the marker for a class the sidebar cannot show
 * individually. It stays false for a class that IS one of the visible rows,
 * so the two active markers never appear together.
 */
export function classesItemActive(pathname: string, visibleClassIds: string[]): boolean {
  const path = pathname.replace(/\/+$/, "") || pathname
  if (path === "/teacher/classes") return true
  const match = path.match(/^\/teacher\/classes\/([^/]+)(?:\/analytics)?$/)
  if (!match) return false
  return !visibleClassIds.includes(match[1])
}

/* ── Shared stat card ────────────────────────────────────────────────────── */

export interface StatCard {
  k: string
  v: string
  unit?: string
  foot?: string
  /** Semantic colour of the big number. */
  valueTone?: "t1" | "accent" | "err"
  /** Semantic colour of the footnote. */
  footTone?: "t2" | "ok" | "err"
}
