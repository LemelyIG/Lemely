import { readFileSync, readdirSync, statSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { relativeTo, sourceFiles, stripComments } from "./support/jsxSource"

/*
 * P3.4 · RTL safety, as a test rather than a promise.
 *
 * The mission's rule from Phase 3 to the end: new and edited styles use
 * logical properties (`margin-inline-start`, `padding-inline`,
 * `inset-inline-end`, `text-align: start`), no hardcoded left/right in layout
 * CSS, and direction-dependent icons flagged with a comment. English is the
 * only language that ships, so nothing visibly breaks when this rule is
 * broken — which is precisely why it needs a test. A rule whose violation has
 * no symptom until a future `dir="rtl"` flip is a rule that quietly decays.
 *
 * Scope is the files Phase 3 created or restyled, listed explicitly rather
 * than globbed over `src/`. Globbing would fail on the ~40 build-era screens
 * Phase 4 has not reached yet, so it would have to be skipped, and a skipped
 * test protects nothing. Phase 4 adds each surface to this list as it
 * migrates it, and the list only ever grows.
 */

const RTL_CLEAN_FILES = [
  // Phase 4, surface 10 — 404 / misc, and the settings lane no surface owned.
  "src/portals/student/screens/Subject.tsx",
  "src/portals/student/screens/Parents.tsx",
  "src/portals/student/screens/Notifications.tsx",
  "src/portals/student/screens/Announcements.tsx",
  "src/portals/student/screens/Onboarding.tsx",
  "src/portals/student/screens/onboarding/SubjectsStep.tsx",
  "src/portals/student/screens/onboarding/QuestionnaireStep.tsx",
  "src/portals/student/screens/placement/PlacementInvite.tsx",
  "src/portals/student/screens/placement/PlacementResult.tsx",
  "src/portals/student/screens/placement/PlacementTest.tsx",
  "src/portals/student/screens/practice/PracticeSet.tsx",
  "src/lib/studentOutcome.ts",
  "src/portals/settings/SettingsFrame.tsx",
  "src/portals/settings/DeviceSettings.tsx",
  "src/portals/settings/NotificationSettings.tsx",
  // P4.7 · the two admin lanes (K-01…K-04, X-01…X-03).
  "src/portals/admin/index.tsx",
  "src/portals/admin/screens/SchoolDashboard.tsx",
  "src/portals/admin/screens/Seats.tsx",
  "src/portals/admin/screens/Teachers.tsx",
  "src/portals/admin/screens/Classes.tsx",
  "src/portals/admin/screens/PlatformConsole.tsx",
  "src/portals/admin/screens/Activations.tsx",
  "src/portals/admin/screens/PipelineHealth.tsx",
  "src/lib/settingsOutcome.ts",
  // Phase 4, surface 9 — the marketing lane, and the Reveal it needed.
  "src/portals/marketing/index.tsx",
  "src/portals/marketing/Landing.tsx",
  "src/portals/marketing/DataHandling.tsx",
  "src/components/ui/reveal.tsx",
  "dev-previews/Directions.tsx",
  "src/routes.tsx",
  // Phase 4, surface 5 — the teacher portal.
  "src/portals/teacher/index.tsx",
  "src/portals/teacher/components/StatCard.tsx",
  "src/portals/teacher/screens/Overview.tsx",
  "src/portals/teacher/screens/AtRiskList.tsx",
  "src/portals/teacher/screens/ClassAnalytics.tsx",
  "src/lib/teacherOutcome.ts",
  "src/lib/severity.ts",
  "src/portals/teacher/screens/Quizzes.tsx",
  "src/portals/teacher/screens/QuizBuilder.tsx",
  "src/portals/teacher/screens/QuizResults.tsx",
  "src/components/ui/confirm-modal.tsx",
  "src/components/CameraCapture.tsx",
  "src/portals/teacher/screens/Grading.tsx",
  "src/portals/teacher/screens/Review.tsx",
  "src/portals/teacher/screens/ReviewItem.tsx",
  "src/portals/teacher/screens/MarkSchemes.tsx",
  "src/portals/teacher/screens/Classes.tsx",
  "src/portals/teacher/screens/ClassDetail.tsx",
  "src/portals/teacher/screens/ClassRoster.tsx",
  "src/portals/teacher/screens/StudentDetail.tsx",
  "src/portals/teacher/screens/Announcements.tsx",
  // Phase 4, surface 6 — the parent portal. `index.tsx` was already listed
  // from Phase 3 and stays listed once.
  "src/lib/parentOutcome.ts",
  "src/portals/parent/screens/Children.tsx",
  "src/portals/parent/screens/ChildOverview.tsx",
  "src/portals/parent/screens/SubjectDetail.tsx",
  "src/portals/parent/screens/Weaknesses.tsx",
  "src/components/ui/weakness-chip.tsx",
  "src/components/ui/trend-sparkline.tsx",
  // Phase 4, surface 8 — auth.
  "src/lib/authOutcome.ts",
  "src/portals/auth/Login.tsx",
  "src/portals/auth/DeviceLimitNotice.tsx",
  "src/portals/auth/ParentLogin.tsx",
  // Kit components created in Phase 3.
  "src/components/ui/breadcrumbs.tsx",
  "src/components/ui/getting-started.tsx",
  "src/components/ui/loading-shapes.tsx",
  "src/components/ui/nav-drawer.tsx",
  "src/components/ui/skip-link.tsx",
  // Kit components Phase 4 touched, surface by surface.
  "src/components/ui/badge.tsx",
  "src/components/ui/card.tsx",
  "src/components/ui/chart-frame.tsx",
  "src/components/ui/lazy-chart.tsx",
  "src/components/ui/line-chart.tsx",
  "src/components/ui/bar-chart.tsx",
  "src/components/ui/boundary-bar.tsx",
  "src/components/ui/file-drop.tsx",
  "src/components/ui/grade-badge.tsx",
  "src/components/ui/mark-display.tsx",
  "src/components/ui/primitives.tsx",
  "src/components/ui/processing-state.tsx",
  "src/components/ui/state-views.tsx",
  "src/components/ui/subject-tag.tsx",
  // Screens and layouts Phase 3 restyled.
  "src/portals/misc/NotFound.tsx",
  "src/portals/student/index.tsx",
  "src/portals/teacher/index.tsx",
  "src/portals/parent/index.tsx",
  "src/portals/student/screens/Overview.tsx",
  "src/portals/teacher/screens/Overview.tsx",
  // Phase 4, surface 2 — the correct-a-paper flow.
  "src/portals/student/screens/CorrectPaper.tsx",
  "src/portals/student/screens/PaperResult.tsx",
  // Phase 4, surface 3 — the study surfaces (classified practice, flashcards,
  // study plans). `PracticePrint.tsx` carried the one real violation this
  // sweep found: a physical `pl-4` indenting the MCQ options on a worksheet.
  "src/components/quiz/QuizTaker.tsx",
  "src/components/ui/input.tsx",
  "src/components/ui/kbd.tsx",
  "src/components/ui/modal.tsx",
  "src/components/ui/progress-bar.tsx",
  "src/components/ui/slider.tsx",
  "src/portals/student/screens/flashcards/FlashcardDecks.tsx",
  "src/portals/student/screens/flashcards/FlashcardReview.tsx",
  "src/portals/student/screens/practice/PracticeGenerator.tsx",
  "src/portals/student/screens/practice/PracticePrint.tsx",
  "src/portals/student/screens/practice/PracticeResult.tsx",
  "src/portals/student/screens/practice/PracticeSet.tsx",
  "src/portals/student/screens/studyplan/StudyPlanSession.tsx",
  "src/portals/student/screens/studyplan/StudyPlanWeek.tsx",
  // Phase 4, surface 4 — gamification (XP, streaks, leaderboards). The
  // confetti in `celebration.tsx` is the interesting case: `transform` has no
  // logical axis, so its inline travel is multiplied by `--lm-dir` in the
  // keyframe rather than expressed in a utility — the same device the mobile
  // drawer's entry uses (P3.4).
  "src/components/ui/celebration.tsx",
  "src/components/ui/xp-streak.tsx",
  "src/portals/student/screens/Friends.tsx",
  "src/portals/student/screens/Profile.tsx",
  "src/portals/student/screens/Standings.tsx",
]

/**
 * Physical-direction Tailwind utilities that have a logical counterpart.
 *
 * Deliberately excludes the block-axis ones (`mt`/`mb`/`pt`/`pb`/`top`/
 * `bottom`/`inset-y`/`border-t`/`border-b`): the block axis does not flip
 * under `dir="rtl"`, so rewriting those buys nothing and would make the rule
 * look arbitrary. `rounded-t`/`rounded-b` are excluded for the same reason.
 */
const PHYSICAL = [
  ["ml-", "ms-"],
  ["mr-", "me-"],
  ["pl-", "ps-"],
  ["pr-", "pe-"],
  ["left-", "start-"],
  ["right-", "end-"],
  ["border-l", "border-s"],
  ["border-r", "border-e"],
  ["rounded-l", "rounded-s"],
  ["rounded-r", "rounded-e"],
  ["text-left", "text-start"],
  ["text-right", "text-end"],
] as const

/**
 * Only look inside `className="..."` / `className={...}` — not at prose.
 *
 * Comments are stripped from the captured expression, which is not fastidious
 * tidying: a `className={cn(...)}` block in this codebase routinely explains
 * *why* it is not using the physical utility, naming it to do so ("`px-[9px]`
 * not `pl-`/`pr-`", "`start-*`, not `left-*`"). Matching those made the check
 * fail on the two files that documented the rule most carefully, which is the
 * worst possible incentive to attach to a lint.
 */
function classNameText(source: string): { line: number; value: string }[] {
  const out: { line: number; value: string }[] = []
  const re = /className=(?:"([^"]*)"|\{([\s\S]*?)\}\s*(?=\/?>|\n\s*[a-zA-Z-]+=))/g
  let match: RegExpExecArray | null
  while ((match = re.exec(source)) !== null) {
    const raw = match[1] ?? match[2] ?? ""
    out.push({
      line: source.slice(0, match.index).split("\n").length,
      value: raw.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/\/\/.*$/gm, ""),
    })
  }
  return out
}

describe("RTL safety on Phase 3 surfaces", () => {
  it.each(RTL_CLEAN_FILES)("%s uses logical properties only", (relative) => {
    const source = readFileSync(join(process.cwd(), relative), "utf8")
    const offences: string[] = []

    for (const { line, value } of classNameText(source)) {
      for (const [physical, logical] of PHYSICAL) {
        // Two boundaries are needed, and missing the second one is how this
        // check first reported `rounded-lg` as a physical `rounded-l`:
        //   - leading: the utility must start a class token, so `mr-` does not
        //     match inside `chart-mr-2`;
        //   - trailing: a prefix that does not already end in `-` must be
        //     followed by a separator, not another letter. `rounded-l` is
        //     physical; `rounded-lg` is a radius and has nothing to do with
        //     direction. Same for `border-l` against a hypothetical
        //     `border-lime`.
        const trailing = physical.endsWith("-") ? "" : "(?![a-zA-Z])"
        const re = new RegExp(
          `(?:^|[\\s"'\`:])(${physical}${trailing}[a-z0-9.\\[\\]/-]*)`,
          "g",
        )
        let hit: RegExpExecArray | null
        while ((hit = re.exec(value)) !== null) {
          offences.push(`${relative}:${line}  ${hit[1]}  ->  use ${logical}…`)
        }
      }
    }

    expect(offences, offences.join("\n")).toEqual([])
  })

  /*
   * `transform` has no logical axis, so any keyframe that moves along the
   * reading direction must multiply by `--lm-dir` rather than hardcode a
   * negative. Without this the nav drawer would slide out of the viewport
   * instead of into it under `dir="rtl"`.
   */
  it("carries the inline axis through --lm-dir in index.css", () => {
    const css = readFileSync(join(process.cwd(), "src/index.css"), "utf8")
    expect(css).toContain("--lm-dir: 1")
    expect(css).toMatch(/\[dir="rtl"\]\s*\{[^}]*--lm-dir:\s*-1/)
    expect(css).toContain("translateX(calc(-100% * var(--lm-dir)))")
  })

  /*
   * The two caret glyphs in `Breadcrumbs` point along the reading direction,
   * so they are the "direction-dependent icons" the rule says must be flagged
   * and must mirror. A caret that keeps pointing right in an RTL layout points
   * backwards through the trail.
   */
  it("mirrors the direction-dependent caret glyphs", () => {
    const source = readFileSync(join(process.cwd(), "src/components/ui/breadcrumbs.tsx"), "utf8")
    expect(source).toContain("rtl:-scale-x-100")
    expect(source).toContain("rtl:scale-x-100")
  })
})

/*
 * P7.1 · The direction-dependent thing a style rule cannot see.
 *
 * Everything above reads styles, because that is where the rule was written:
 * logical properties, no hardcoded left/right, mirrored icon classes. Fourteen
 * buttons and links across the teacher portal ended their label with a literal
 * `"→"` inside the string — "Open review queue →", "Save & continue →" — and
 * not one of the rules above could see them, because they are not styles. They
 * are characters.
 *
 * A horizontal arrow is direction-dependent by definition, and it is the one
 * form of direction-dependence that a later `dir="rtl"` flip **cannot repair**:
 * `rtl:-scale-x-100` transforms a box, and a character in a text node has no
 * box of its own. The bidi algorithm does not mirror U+2192 either. So these
 * would have stayed pointing away from the reading direction, silently, with
 * the gate that exists to prevent exactly that reporting green.
 *
 * `ForwardArrow` in `components/ui/inline-arrow.tsx` is the replacement and it
 * mirrors. This rule walks the whole tree rather than a list, because the
 * standing lesson from surface 10 is that a screen no list claims is a screen
 * no gate reads, and a hand-maintained list is how the fifteenth call site
 * would arrive unnoticed.
 */
describe("no direction-dependent glyph is baked into UI copy", () => {
  const HORIZONTAL = /[→←⇒⇐➔➜▶◀►◄»«]/u

  it("uses ForwardArrow, never an arrow character, in any .tsx", () => {
    const offenders: string[] = []
    for (const file of sourceFiles(join(process.cwd(), "src"))) {
      const source = stripComments(readFileSync(file, "utf8"))
      source.split("\n").forEach((line, i) => {
        if (HORIZONTAL.test(line)) {
          offenders.push(`${relativeTo(process.cwd(), file)}:${i + 1} — ${line.trim().slice(0, 70)}`)
        }
      })
    }
    expect(offenders).toEqual([])
  })
})

/*
 * A guard on the guard. If `RTL_CLEAN_FILES` ever lists a path that has been
 * moved or renamed, the `it.each` above would still pass by reading a file
 * that no longer exists... it would throw, in fact. This asserts the friendlier
 * failure, and catches the opposite mistake: a Phase 3 kit component added to
 * `components/ui/` without being added to the list.
 */
describe("the RTL file list stays honest", () => {
  const PHASE_3_KIT = [
    "breadcrumbs.tsx",
    "getting-started.tsx",
    "loading-shapes.tsx",
    "nav-drawer.tsx",
    "skip-link.tsx",
  ]

  it.each(RTL_CLEAN_FILES)("%s exists", (relative) => {
    expect(statSync(join(process.cwd(), relative)).isFile()).toBe(true)
  })

  it("covers every component Phase 3 added to the kit", () => {
    const present = readdirSync(join(process.cwd(), "src/components/ui"))
    for (const file of PHASE_3_KIT) {
      expect(present, `${file} vanished from the kit`).toContain(file)
      expect(
        RTL_CLEAN_FILES,
        `${file} is in the kit but not covered by the RTL check`,
      ).toContain(`src/components/ui/${file}`)
    }
  })
})
