import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * The compat-layer gate.
 *
 * `index.css` carries a documented, temporary block of build-era token aliases
 * (`--t1`, `--surface`, `--border`, `--font-serif`, the `text-dense-*` rungs).
 * They exist so un-migrated screens pick up Study Notebook *values* instead of
 * staying Material-3 until their Phase 4 turn, and the block dies when the last
 * call site does.
 *
 * That plan only works if a migrated file cannot quietly acquire a new alias
 * later. This list is the set of files that have completed their migration; the
 * assertion is that none of them names a compat alias. Like `RTL_CLEAN_FILES`
 * in `rtlSafety.test.ts`, **the list only grows** — a file is appended when its
 * surface lands and is never removed.
 *
 * Why a source gate rather than a visual check: the aliases resolve to the
 * correct values today, so a compat class renders *identically* to its Study
 * Notebook counterpart. Nothing on screen, in a screenshot, or in a contrast
 * measurement can distinguish them. The only place the difference is visible is
 * the source, which is where this looks.
 *
 * This is the same failure shape as D4.1's `--font-serif` finding: a class that
 * is well-formed, resolves to *something*, and is therefore invisible to every
 * gate that looks at rendered output.
 */
const MIGRATED_FILES = [
  // Phase 4, surface 1 — the student dashboard.
  "src/portals/student/screens/Overview.tsx",
  // Phase 4, surface 2 — the correct-a-paper flow.
  "src/portals/student/screens/CorrectPaper.tsx",
  "src/portals/student/screens/PaperResult.tsx",
  // Phase 4, surface 3 — the study surfaces.
  "src/components/quiz/QuizTaker.tsx",
  "src/portals/student/screens/flashcards/FlashcardDecks.tsx",
  "src/portals/student/screens/flashcards/FlashcardReview.tsx",
  "src/portals/student/screens/practice/PracticeGenerator.tsx",
  "src/portals/student/screens/practice/PracticePrint.tsx",
  "src/portals/student/screens/practice/PracticeResult.tsx",
  "src/portals/student/screens/studyplan/StudyPlanSession.tsx",
  "src/portals/student/screens/studyplan/StudyPlanWeek.tsx",
  // Phase 4, surface 4 — gamification (XP, streaks, leaderboards).
  "src/components/ui/celebration.tsx",
  "src/components/ui/xp-streak.tsx",
  "src/portals/student/screens/Friends.tsx",
  "src/portals/student/screens/Profile.tsx",
  "src/portals/student/screens/Standings.tsx",
  // Phase 4, surface 5 — the teacher portal.
  "src/portals/teacher/index.tsx",
  "src/portals/teacher/components/StatCard.tsx",
  "src/portals/teacher/screens/Overview.tsx",
  "src/portals/teacher/screens/AtRiskList.tsx",
  "src/portals/teacher/screens/ClassAnalytics.tsx",
  "src/lib/teacherOutcome.ts",
  "src/lib/severity.ts",
]

/**
 * Build-era class names and the Study Notebook name that replaces each.
 *
 * Ordered longest-prefix-first within a family so `bg-surface-2` is reported as
 * itself rather than as `bg-surface`, which is the same ordering trap the bulk
 * substitution had to avoid.
 */
const COMPAT_CLASSES: [pattern: RegExp, replacement: string][] = [
  [/\btext-t1\b/, "text-ink"],
  [/\btext-t2\b/, "text-ink-muted"],
  [/\btext-t3\b/, "text-ink-faint"],
  [/\bbg-bg\b/, "bg-paper"],
  [/\bbg-surface-2\b/, "bg-paper-sunk"],
  [/\bbg-surface\b/, "bg-paper-raised"],
  [/\bborder-border\b/, "border-rule"],
  [/\bbg-ok-bg\b/, "bg-ok-wash"],
  [/\bbg-warn-bg\b/, "bg-warn-wash"],
  [/\bbg-err-bg\b/, "bg-err-wash"],
  [/\bbg-accent-subtle\b/, "bg-accent-wash"],
  [/\btext-accent-subtle-on\b/, "text-accent-ink"],
  // `font-serif` is the D4.1 case specifically: it was never a token, resolved
  // to Tailwind's default Georgia stack for the whole build era, and is aliased
  // to `--font-display` only as a stopgap. The type rungs carry their own
  // family, so a migrated file needs no family utility at all.
  [/\bfont-serif\b/, "a text-display-* rung, which sets the family itself"],
  [/\bleading-display\b/, "nothing — the text-display-* rungs set line-height"],
  [/\btext-dense-sm\b/, "text-body-sm"],
  [/\btext-dense-lg\b/, "text-body-md"],
  [/\btext-dense\b/, "text-body-sm"],
  [/\btext-display-xs\b/, "text-display-sm"],
  [/\btext-label-sm\b/, "text-eyebrow"],
  [/\btext-metadata\b/, "text-data-sm"],
]

function sourceOf(relative: string): string {
  return readFileSync(join(process.cwd(), relative), "utf8")
}

/**
 * The source with every comment blanked out, line numbering preserved.
 *
 * Several migrated files legitimately *name* the class they stopped using, in a
 * comment explaining why it went away — this file's own subject matter makes
 * that unavoidable. A gate that punished the explanation would push exactly the
 * commentary a later reader needs out of the code, so comments are stripped and
 * only real class strings are judged.
 *
 * A per-line "does it start with `*`" test is NOT enough, and assuming it was
 * is what made this gate first report `StudyPlanWeek.tsx:112` — the *middle*
 * line of a JSX `{/* … *​/}` block, whose continuation lines start with ordinary
 * prose. Block state has to be tracked across lines, so it is.
 */
function codeLines(source: string): { line: string; number: number }[] {
  let inBlock = false

  return source.split("\n").map((raw, index) => {
    let out = ""
    let i = 0
    while (i < raw.length) {
      if (inBlock) {
        if (raw.startsWith("*/", i)) {
          inBlock = false
          i += 2
        } else {
          i += 1
        }
        continue
      }
      if (raw.startsWith("/*", i)) {
        inBlock = true
        i += 2
        continue
      }
      if (raw.startsWith("//", i)) break
      out += raw[i]
      i += 1
    }
    return { line: out, number: index + 1 }
  })
}

describe("Study Notebook migration", () => {
  it.each(MIGRATED_FILES)("%s names no compat-layer token", (relative) => {
    const source = sourceOf(relative)
    const offences: string[] = []

    for (const { line, number } of codeLines(source)) {
      for (const [pattern, replacement] of COMPAT_CLASSES) {
        if (pattern.test(line)) {
          offences.push(
            `${relative}:${number} uses ${pattern.source.replace(/\\b/g, "")} — use ${replacement}`,
          )
          break
        }
      }
    }

    expect(offences).toEqual([])
  })

  /**
   * The Read lane's column, pinned (DESIGN.md §2 and §13).
   *
   * Before this surface the eight study screens carried FOUR different
   * container widths — 560, 640, 720 and 840 — so the same lane rendered at a
   * different measure depending on which link a student had followed. They
   * share the `lm-read` utility now, and this fails if a Read screen goes back
   * to picking its own width.
   */
  const READ_LANE_SCREENS = [
    "src/portals/student/screens/flashcards/FlashcardDecks.tsx",
    "src/portals/student/screens/flashcards/FlashcardReview.tsx",
    "src/portals/student/screens/practice/PracticeGenerator.tsx",
    "src/portals/student/screens/practice/PracticePrint.tsx",
    "src/portals/student/screens/practice/PracticeResult.tsx",
    "src/portals/student/screens/studyplan/StudyPlanSession.tsx",
    "src/portals/student/screens/studyplan/StudyPlanWeek.tsx",
  ]

  it.each(READ_LANE_SCREENS)("%s takes its column from lm-read", (relative) => {
    const source = sourceOf(relative)
    expect(source).toContain("lm-read")
    // An arbitrary pixel max-width is how the four measures happened.
    expect(source).not.toMatch(/max-w-\[\d+px\]/)
  })

  /**
   * `lm-read` and `lm-prose` have to exist for the above to mean anything. A
   * Tailwind class that resolves to nothing is silent — exactly the way
   * `font-serif` was silent — so the definitions are asserted, not assumed.
   */
  it("defines lm-read and lm-prose in the stylesheet", () => {
    const css = sourceOf("src/index.css")
    expect(css).toMatch(/\.lm-read\s*\{/)
    expect(css).toMatch(/\.lm-prose\s*\{/)
    // §13 fixes the Read container at 680px and §2/§4.2 cap prose at 65ch.
    expect(css).toMatch(/\.lm-read\s*\{[^}]*max-width:\s*680px/)
    expect(css).toMatch(/\.lm-prose\s*\{[^}]*max-width:\s*65ch/)
  })

  /**
   * DESIGN.md §9.2: animate only `transform` and `opacity`.
   *
   * The study plan's week bar drove its fill with `transition-[width]`, which
   * is a layout-animating property on the element that changes every time a
   * session is ticked off. It is C-24 `ProgressBar` now. This catches the
   * arbitrary-property form specifically, since a plain `transition-all` is
   * caught by review and `transition-[width]` reads as deliberate.
   */
  it.each(MIGRATED_FILES)("%s animates no layout property", (relative) => {
    const offending = codeLines(sourceOf(relative)).filter(({ line }) =>
      /transition-\[(width|height|top|left|right|bottom|inset)/.test(line),
    )
    expect(offending.map(({ number }) => `${relative}:${number}`)).toEqual([])
  })
})
