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
  icon: "overview" | "grading" | "classes" | "atRisk" | "schemes" | "quizzes"
  /** Index route match (Overview lives at /teacher). */
  end?: boolean
}

export const navItems: NavItem[] = [
  { to: "/teacher", label: "Overview", icon: "overview", end: true },
  { to: "/teacher/grading", label: "Grading", icon: "grading" },
  { to: "/teacher/classes", label: "Classes", icon: "classes" },
  { to: "/teacher/at-risk", label: "At-risk students", icon: "atRisk" },
  { to: "/teacher/schemes", label: "Mark schemes", icon: "schemes" },
  { to: "/teacher/quizzes", label: "AI quizzes", icon: "quizzes" },
]

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
