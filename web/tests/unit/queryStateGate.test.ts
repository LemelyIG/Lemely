import { readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { relativeTo, sourceFiles } from "./support/jsxSource"

/**
 * Loading/error primitives PR, part D · the `<QueryState>` adoption gate.
 *
 * ── Why this gate exists ────────────────────────────────────────────────────
 *
 * `query-state.tsx`'s own header names the defect this closes: roughly
 * twenty-five screens each hand-wrote their own pending/error/empty branches,
 * small enough to differ from their neighbours without anyone noticing at
 * review time, and at least two of them (per that header) shipped rendering a
 * machine's raw error message because nothing connected "a shared pattern now
 * exists" to "screens written before it should be revisited." A component
 * that a screen can simply not import does not fix that on its own — the
 * fix is a gate that notices the screen that skipped it, which is this file.
 *
 * `Overview.tsx` is the reference conversion this same PR ships alongside the
 * component: it is deliberately NOT on the allowlist below, and the last
 * `describe` block in this file exists specifically to prove the detector
 * recognises it as both data-loading and compliant. If someone breaks the
 * detector — loosens the hook-import regex, typos the `<QueryState` check —
 * that canary is what says so, rather than the gate quietly reporting green
 * because it stopped looking at the one screen already known to comply.
 *
 * ── What "loads data" means here ────────────────────────────────────────────
 *
 * A screen loads data when it imports a hook-shaped name from `@/lib/hooks/`
 * (every export in that directory that is not itself a hook — `uploadPaper`,
 * `normalizeInviteCode`, the `*Options`/`*Variables` interfaces — fails the
 * `use[A-Z]` check and is correctly ignored) or calls `useQuery`,
 * `useQueries` or `useInfiniteQuery` directly. No screen in this repo does
 * the latter today — every data hook lives behind `@/lib/hooks/*` — but the
 * PR's own definition of done names it, and a screen that reaches past the
 * hooks layer straight to react-query is exactly the kind of drift a
 * text-only gate should still catch.
 *
 * This deliberately over-counts relative to "fetches on mount": a screen that
 * imports only a mutation hook (`useCreateClass`, `useMintClassInviteCode`)
 * is flagged too, because the detector cannot tell a query export from a
 * mutation export without importing `@/lib/hooks/*` and inspecting its
 * return type — which would pull react-query and its whole dependency graph
 * into a node-environment test that has neither. A screen wrongly flagged as
 * data-loading fails safe: it lands on the allowlist below with an honest
 * reason, never silently passes as compliant.
 *
 * ── Why source text, not an import ──────────────────────────────────────────
 *
 * Screens pull in React, react-router and the component tree; importing one
 * in this suite would drag all of that into `environment: "node"`, which
 * `vitest.config.ts` deliberately has no jsdom under (see that file's own
 * header). Reading the file as text and pattern-matching it is the same
 * trade `hallmarkStamp.test.ts` and `notFoundFallback.test.ts` already make.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const SCREENS_ROOT = join(ROOT, "src", "portals")
const QUIZ_ROOT = join(ROOT, "src", "components", "quiz")

/**
 * Matches `import { a, b } from "@/lib/hooks/whatever"` (optionally
 * `import type { … }`), spanning multiple lines — several call sites in this
 * repo wrap a long named-import list across lines (e.g.
 * `admin/screens/Teachers.tsx`), and `[^}]*` already matches newlines inside
 * a character class with no `s` flag needed, so this works unmodified either
 * way. Global so a screen with more than one `@/lib/hooks/*` import is fully
 * read rather than stopping at the first match.
 */
const HOOKS_IMPORT = /import\s+(?:type\s+)?\{([^}]*)\}\s*from\s*["']@\/lib\/hooks\/[^"']+["']/gs

/** A direct react-query call, for the screen that reaches past the hooks
 * layer entirely (see module header — none does today, but the PR's
 * definition of done names this explicitly). */
const DIRECT_QUERY_CALL = /\b(?:useQuery|useQueries|useInfiniteQuery)\s*\(/

/**
 * True when `source` names at least one hook (an identifier starting
 * `use` + an uppercase letter, matching every export in `src/lib/hooks/`
 * that is actually a hook) among the names imported from `@/lib/hooks/*`.
 *
 * Handles `useFoo as useBar` (checks the imported name, left of `as`, since
 * that is what determines whether `@/lib/hooks/*` exported a hook — the
 * local alias could be renamed to anything) and a `type Foo` entry sharing
 * the same braces (stripped before the check, since a type import loads no
 * data at runtime).
 */
function importsAHook(source: string): boolean {
  for (const match of source.matchAll(HOOKS_IMPORT)) {
    const names = match[1]
      .split(",")
      .map((n) => n.trim())
      .filter(Boolean)
    for (const name of names) {
      const imported = name.replace(/^type\s+/, "").split(/\s+as\s+/)[0]?.trim() ?? ""
      if (/^use[A-Z]/.test(imported)) return true
    }
  }
  return false
}

/** A screen "loads data" per the PR's definition of done — see module
 * header for what each half catches and why both are needed. */
function loadsData(source: string): boolean {
  return importsAHook(source) || DIRECT_QUERY_CALL.test(source)
}

/**
 * A screen complies once it both imports `QueryState` from the real module
 * (not some other `QueryState`, and not just a re-export naming it) and
 * actually renders it. Checking only the import would pass a screen that
 * imports the component and never uses it — dead weight, not adoption — and
 * checking only `<QueryState` would pass a screen that happens to define or
 * import a same-named local component from somewhere else.
 */
function usesQueryState(source: string): boolean {
  const importsQueryState =
    /import\s*\{[^}]*\bQueryState\b[^}]*\}\s*from\s*["']@\/components\/ui\/query-state["']/s.test(
      source,
    )
  const rendersQueryState = /<QueryState\b/.test(source)
  return importsQueryState && rendersQueryState
}

/*
 * Every screen already converted to `QueryState` as of this PR, seeded by
 * actually running the detector above against the tree on 2026-09-02 — not
 * guessed and not copied from a design doc — with `Overview.tsx` excluded
 * on purpose (see module header). A later PR ("the per-screen sweep") is
 * where these get converted one at a time; each conversion deletes its own
 * entry here rather than the whole list being cleared in one sitting, for
 * the same reason `hallmarkStamp.test.ts` refuses to back-fill 33 stamps at
 * once: a conversion nobody reviewed screen-by-screen is not a conversion,
 * it is this gate lying about the state of the product.
 *
 * This list may shrink and must never grow. A NEW screen that loads data
 * must use `QueryState` from the day it is written — it has no excuse to
 * land here, because unlike the 53 below it was never hand-rolling its own
 * pending/error branches to begin with.
 */
const ALLOWLIST: { path: string; reason: string }[] = [
  {
    path: "src/components/quiz/QuizTaker.tsx",
    reason: "shared quiz-taking surface, converted in the per-screen sweep (PR 3)",
  },
  { path: "src/portals/admin/screens/Activations.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/admin/screens/Classes.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/admin/screens/PipelineHealth.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/admin/screens/PlatformConsole.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/admin/screens/SchoolDashboard.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/admin/screens/Schools.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/admin/screens/Seats.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/admin/screens/Teachers.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  {
    path: "src/portals/auth/JoinWithCode.tsx",
    reason: "route-level surface outside portals/**/screens, converted in the per-screen sweep (PR 3)",
  },
  {
    path: "src/portals/auth/SignupDetails.tsx",
    reason: "route-level surface outside portals/**/screens, converted in the per-screen sweep (PR 3)",
  },
  {
    path: "src/portals/auth/VerifyEmail.tsx",
    reason: "route-level surface outside portals/**/screens, converted in the per-screen sweep (PR 3)",
  },
  { path: "src/portals/parent/screens/ChildOverview.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/parent/screens/Children.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/parent/screens/SubjectDetail.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/parent/screens/Weaknesses.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  {
    path: "src/portals/settings/DeviceSettings.tsx",
    reason: "route-level surface outside portals/**/screens, converted in the per-screen sweep (PR 3)",
  },
  {
    path: "src/portals/settings/NotificationSettings.tsx",
    reason: "route-level surface outside portals/**/screens, converted in the per-screen sweep (PR 3)",
  },
  { path: "src/portals/student/screens/Announcements.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/CorrectPaper.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/Friends.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/Notifications.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/Onboarding.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/PaperResult.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/Parents.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/Profile.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/Standings.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/Subject.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/flashcards/FlashcardDecks.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/flashcards/FlashcardReview.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/placement/PlacementInvite.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/placement/PlacementResult.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/practice/PracticeGenerator.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/practice/PracticePrint.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/practice/PracticeResult.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/studyplan/StudyPlanSession.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/student/screens/studyplan/StudyPlanWeek.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/Announcements.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/AtRiskList.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/ClassAnalytics.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/ClassDetail.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/ClassRoster.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/Classes.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/CreateFirstClass.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/Grading.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/MarkSchemes.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/Overview.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/QuizBuilder.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/QuizResults.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/Quizzes.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/Review.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/ReviewItem.tsx", reason: "converted in the per-screen sweep (PR 3)" },
  { path: "src/portals/teacher/screens/StudentDetail.tsx", reason: "converted in the per-screen sweep (PR 3)" },
]

const ALLOWLISTED_PATHS = new Set(ALLOWLIST.map((entry) => entry.path))

/**
 * The gated surface is every `.tsx` under `portals/**\/screens/**`, plus
 * every `.tsx` directly under `portals/settings/`, `portals/auth/` and
 * `components/quiz/` — not every `.tsx` under `portals/`: `sourceFiles`
 * walks the whole subtree, which also holds `index.tsx` layout shells and
 * portal-local components that never render a route or a pending/error
 * state of their own.
 *
 * Two things widened this from "just `/screens/`" (its original, narrower
 * shape):
 *
 *  - `PlacementTest.tsx` and `PracticeSet.tsx` (both under `/screens/`)
 *    import no hook from `@/lib/hooks/` themselves — they delegate all
 *    data-loading to `QuizTaker.tsx`, which hand-rolls its own
 *    pending/error branches around `useStudentQuizTake`. A gate that only
 *    ever reads `/screens/` files never reaches that component, so a
 *    genuinely hand-rolled pending/error branch sat one hop outside the
 *    net. `components/quiz/` closes that gap.
 *  - Several route-level surfaces render outside any portal's
 *    `screens/` directory entirely: `portals/settings/DeviceSettings.tsx`,
 *    `portals/settings/NotificationSettings.tsx`,
 *    `portals/auth/VerifyEmail.tsx`, `portals/auth/JoinWithCode.tsx` and
 *    `portals/auth/SignupDetails.tsx` are each routed to directly
 *    (`routes.tsx`), not composed from inside a screen, so the original
 *    `/screens/`-only filter never saw them either.
 *
 * `portals/**\/index.tsx` layout shells are deliberately still excluded:
 * a layout renders its portal's persistent chrome (nav, sidebar) from a
 * query, but that query drives what to *show*, not a page-level
 * pending/error state to compose — there is no screen-shaped "loading"
 * moment a layout itself owns, `<Outlet/>` renders whatever screen is
 * routed to regardless. `portals/marketing/` is excluded for a different
 * reason: it is static landing/legal content with no data-loading screens
 * at all, checked by `loadsData` the same as anything else — it merely
 * never trips it.
 */
const SCREENS = [...sourceFiles(SCREENS_ROOT), ...sourceFiles(QUIZ_ROOT)]
  .map((file) => ({ path: relativeTo(ROOT, file), source: readFileSync(file, "utf8") }))
  .filter(
    (f) =>
      f.path.includes("/screens/") ||
      f.path.startsWith("src/portals/settings/") ||
      f.path.startsWith("src/portals/auth/") ||
      f.path.startsWith("src/components/quiz/"),
  )

describe("every data-loading screen uses QueryState or is allowlisted", () => {
  it("has no unlisted screen still hand-rolling its own pending/error branches", () => {
    const offenders = SCREENS.filter(
      (f) => loadsData(f.source) && !usesQueryState(f.source) && !ALLOWLISTED_PATHS.has(f.path),
    ).map((f) => f.path)
    expect(
      offenders,
      "a data-loading screen must call <QueryState> or be named on ALLOWLIST with a reason",
    ).toEqual([])
  })

  /*
   * A deleted screen must leave the list, the same discipline
   * `hallmarkStamp.test.ts` applies to `UNSTAMPED_KIT`: a stale entry does
   * not merely do nothing, it hides the fact that nobody re-checked the list
   * since the file it names stopped existing.
   */
  it("names no screen that no longer exists on disk", () => {
    const missing = ALLOWLIST.filter(
      (entry) => !statSync(join(ROOT, entry.path), { throwIfNoEntry: false })?.isFile(),
    ).map((entry) => entry.path)
    expect(missing, "listed but gone; delete the entry").toEqual([])
  })

  /*
   * Shrink-only discipline. An entry that has since been converted to
   * `QueryState` must be deleted from ALLOWLIST rather than left in place —
   * a compliant screen sitting on this list is not wrong today, but it is
   * exactly how the list quietly stops shrinking: the per-screen sweep PR
   * converts a screen, forgets the one-line deletion here, and the next
   * ten screens pile up behind a gate that no longer notices anything new
   * because the loud "did you seed this honestly" signal (this assertion)
   * has already gone stale once and nobody re-read it.
   */
  it("has no allowlist entry that has since become compliant", () => {
    const stale = ALLOWLIST.filter((entry) => {
      const absolute = join(ROOT, entry.path)
      if (!statSync(absolute, { throwIfNoEntry: false })?.isFile()) return false
      return usesQueryState(readFileSync(absolute, "utf8"))
    }).map((entry) => entry.path)
    expect(stale, "now uses QueryState; delete the entry so the list keeps shrinking").toEqual([])
  })

  /*
   * The mirror check: an entry that no longer loads data by the detector's
   * own rule is a stale entry too, just one that hides differently — it
   * inflates ALLOWLIST with a screen the gate would not have flagged in the
   * first place, which is how a future audit of "why is this here" turns up
   * nothing and the list's count stops meaning what it claims to.
   */
  it("names only screens the detector actually flags as data-loading", () => {
    const notLoading = ALLOWLIST.filter((entry) => {
      const absolute = join(ROOT, entry.path)
      if (!statSync(absolute, { throwIfNoEntry: false })?.isFile()) return false
      return !loadsData(readFileSync(absolute, "utf8"))
    }).map((entry) => entry.path)
    expect(
      notLoading,
      "the detector no longer considers this screen data-loading; delete the entry",
    ).toEqual([])
  })
})

describe("the detector itself — canary and false-positive checks", () => {
  /*
   * `Overview.tsx` is the one screen this PR actually converts, deliberately
   * left off ALLOWLIST above. If a future edit to either regex breaks
   * detection — loosens `HOOKS_IMPORT` so nothing matches, or the
   * `<QueryState` check stops recognising the real render — every other
   * assertion in this file could still pass for the wrong reason (an empty
   * `offenders` list from a detector that flags nothing is indistinguishable
   * from one that flags everything correctly). This is the one test that
   * fails loudly instead.
   */
  it("detects Overview.tsx as both data-loading and QueryState-compliant", () => {
    const overview = SCREENS.find((f) => f.path === "src/portals/student/screens/Overview.tsx")
    expect(overview, "Overview.tsx should be walked as a screen").toBeDefined()
    expect(loadsData(overview!.source)).toBe(true)
    expect(usesQueryState(overview!.source)).toBe(true)
  })

  /*
   * `@/lib/hooks/*` is not exclusively hooks — `uploadPaper`,
   * `normalizeInviteCode`, `isSeatQuotaExceededError` and several `*Options`/
   * `*Variables` interfaces live there too (see module header). A screen
   * that imports only one of those must not be counted as data-loading, or
   * this gate would demand `<QueryState>` from a screen that never renders a
   * pending/error branch to begin with. Built from a string literal rather
   * than a real file, per the brief: the point is the regex's own behaviour
   * on a shape that may not currently occur anywhere in the tree, not a
   * screen this repo happens to already have.
   */
  it("does not flag a screen importing only non-hook helpers from @/lib/hooks/", () => {
    const source = `
      import { uploadPaper, normalizeInviteCode } from "@/lib/hooks/useTeacherApi"
      import type { CreateSchoolAdminVariables } from "@/lib/hooks/useAdminApi"

      export function Helper() {
        return uploadPaper && normalizeInviteCode ? null : null
      }
    `
    expect(loadsData(source)).toBe(false)
  })
})
