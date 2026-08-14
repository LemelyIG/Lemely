import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * The resolves-to-nothing gate.
 *
 * D4.1 found `--font-serif` had never been a token, so ~20 call sites across
 * five screens rendered Georgia instead of Newsreader for the whole build era.
 * P4.4 found the same shape again in a different family: **`text-display` is
 * not a class.** Nothing in `index.css` defines it, no `--text-display` or
 * `--color-display` exists for Tailwind to generate it from, and the shipped
 * bundle contains zero rules matching it — verified by grepping
 * `dist/assets/*.css`, not by reasoning about it. Four `<h1>`s carried it:
 * `Profile`, `Standings`, `Friends` and `Announcements`. All four rendered at
 * the browser's default h1 in the body face rather than at §4.2's `display-lg`
 * in Newsreader.
 *
 * Twice is a pattern, so this is the gate for the pattern rather than for the
 * two instances.
 *
 * **Why no existing gate caught either one.** They are all looking somewhere
 * else:
 *   - the token gate greps for raw hex/oklch *bypassing* the token block, and
 *     a missing class contains no raw value;
 *   - `studyNotebookMigration.test.ts` checks that migrated files name no
 *     *build-era* class, and a class that does not exist at all is not on that
 *     list;
 *   - contrast tests measure declared tokens, and this one was never declared;
 *   - screenshots and axe see a rendered page that looks plausible, because a
 *     heading with no size class is still a heading.
 *
 * A well-formed class name that resolves to nothing is the one defect class
 * that is invisible from every direction except this one: comparing the names
 * the source uses against the names the stylesheet defines.
 *
 * P4.5 found it a third time, in the family this gate did not scan: `lm-head`
 * and `lm-body` on the student shell, in a file already on the list below. See
 * `LM_PREFIX` for that one.
 *
 * **Scope, stated rather than implied.** This checks the five families where
 * the design system owns the vocabulary — `text-`, `bg-`, `border-`, `font-`
 * and `lm-`. It does not attempt to validate all of Tailwind; the built-in
 * utilities are allow-listed by shape below. It reports a name only when it
 * matches none of the ways a class in those families can legitimately resolve,
 * which is exactly the condition all three real defects met.
 */

const SCANNED_FILES = [
  // Phase 4, surface 10 — 404 / misc, and the settings lane no surface owned.
  "src/portals/settings/SettingsFrame.tsx",
  "src/portals/settings/DeviceSettings.tsx",
  "src/portals/settings/NotificationSettings.tsx",
  "src/lib/settingsOutcome.ts",
  "src/portals/misc/NotFound.tsx",
  // Phase 4, surface 9 — the marketing lane, and the Reveal it needed.
  "src/portals/marketing/index.tsx",
  "src/portals/marketing/Landing.tsx",
  "src/components/ui/reveal.tsx",
  "dev-previews/Directions.tsx",
  "src/routes.tsx",
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
  // Phase 4, surface 4 — gamification.
  "src/components/ui/celebration.tsx",
  "src/components/ui/xp-streak.tsx",
  "src/portals/student/index.tsx",
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
  "src/portals/teacher/screens/Quizzes.tsx",
  "src/portals/teacher/screens/QuizBuilder.tsx",
  "src/portals/teacher/screens/QuizResults.tsx",
  "src/components/ui/confirm-modal.tsx",
  "src/portals/teacher/screens/Grading.tsx",
  "src/portals/teacher/screens/Review.tsx",
  "src/portals/teacher/screens/ReviewItem.tsx",
  "src/portals/teacher/screens/MarkSchemes.tsx",
  "src/portals/teacher/screens/Classes.tsx",
  "src/portals/teacher/screens/ClassDetail.tsx",
  "src/portals/teacher/screens/ClassRoster.tsx",
  "src/portals/teacher/screens/StudentDetail.tsx",
  "src/portals/teacher/screens/Announcements.tsx",
  // Phase 4, surface 6 — the parent portal.
  "src/lib/parentOutcome.ts",
  "src/portals/parent/index.tsx",
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
]

const CSS_PATH = "src/index.css"

function read(relative: string): string {
  return readFileSync(join(process.cwd(), relative), "utf8")
}

/** Every class defined literally in the stylesheet, e.g. `.text-display-lg`. */
function literalClasses(css: string): Set<string> {
  const found = new Set<string>()
  // `:` is a terminator alongside `,` and `{` because a rule may reach the
  // class through a pseudo-element and still be what defines it: `.lm-scroll`
  // exists in the stylesheet only as `.lm-scroll::-webkit-scrollbar`. Without
  // this the `lm-` family check below would report a class that demonstrably
  // does emit rules.
  for (const match of css.matchAll(/\.([a-z0-9][a-z0-9-]*)\s*(?:,|\{|:)/gi)) {
    found.add(match[1])
  }
  return found
}

/**
 * Every custom property the stylesheet declares, without its `--` prefix.
 *
 * Tailwind v4 generates a utility per `@theme` variable, so `--color-ink`
 * yields `text-ink`/`bg-ink`/`border-ink` and `--font-display` yields
 * `font-display`. Reading the declarations is therefore how we know which
 * generated utilities exist — and `--font-serif`'s absence from this set is
 * precisely what D4.1 was.
 */
function declaredVars(css: string): Set<string> {
  const found = new Set<string>()
  for (const match of css.matchAll(/--([a-z0-9][a-z0-9-]*)\s*:/gi)) {
    found.add(match[1])
  }
  return found
}

/** Tailwind built-ins in these families that are not driven by a theme var. */
const BUILT_IN = new Set([
  // text-*
  "text-left", "text-center", "text-right", "text-justify", "text-start",
  "text-end", "text-wrap", "text-nowrap", "text-balance", "text-pretty",
  "text-ellipsis", "text-clip", "text-transparent", "text-current",
  "text-inherit", "text-white", "text-black",
  "text-xs", "text-sm", "text-base", "text-lg", "text-xl", "text-2xl",
  "text-3xl", "text-4xl", "text-5xl", "text-6xl", "text-7xl", "text-8xl",
  "text-9xl",
  // bg-*
  "bg-transparent", "bg-current", "bg-inherit", "bg-white", "bg-black",
  "bg-none", "bg-cover", "bg-contain", "bg-center", "bg-fixed", "bg-local",
  "bg-scroll", "bg-repeat", "bg-no-repeat", "bg-clip-border",
  "bg-clip-padding", "bg-clip-content", "bg-clip-text", "bg-origin-border",
  "bg-origin-padding", "bg-origin-content", "bg-bottom", "bg-top", "bg-left",
  "bg-right",
  // border-*
  "border-transparent", "border-current", "border-inherit", "border-white",
  "border-black", "border-solid", "border-dashed", "border-dotted",
  "border-double", "border-hidden", "border-none", "border-collapse",
  "border-separate", "border-spacing",
  // font-*
  "font-thin", "font-extralight", "font-light", "font-normal", "font-medium",
  "font-semibold", "font-bold", "font-extrabold", "font-black",
  "font-sans", "font-serif", "font-mono", "font-stretch",
])

/**
 * `font-serif` is on the built-in list above and is ALSO the D4.1 defect. Both
 * are true and the resolution is not to special-case it here: it resolves to
 * Tailwind's default Georgia stack, so it is not "a class that resolves to
 * nothing" — it is a class that resolves to the *wrong* thing, which is a
 * different defect with a different gate. `studyNotebookMigration.test.ts`
 * already forbids it by name in migrated files. This gate would have caught
 * `text-display`; that one catches `font-serif`. Neither alone covers both.
 */
const PREFIXES = ["text-", "bg-", "border-", "font-", "lm-"]

/**
 * `lm-` is the fifth family, added by P4.5 because the shape recurred a third
 * time — and this time inside the gate's own blind spot.
 *
 * `lm-head` and `lm-body` were on the student shell's `<header>` and `<main>`,
 * in a file this list already scanned, and neither is defined anywhere.
 * Verified in the shipped bundle rather than reasoned about: `.lm-read`,
 * `.lm-screen` and `.lm-scroll` each emit rules in `dist/assets/*.css` and
 * those two emit zero. Nothing selected on them either, in source, tests,
 * scripts or the capture harness, so they were removed rather than defined.
 *
 * The reason the existing gate could not see them is worth stating: it checked
 * the four families where *Tailwind* owns the vocabulary, and `lm-` is the one
 * family where the project owns it outright. That makes it the easiest family
 * to check, not the hardest — there is exactly one legitimate route, a literal
 * `.lm-x` rule in `index.css`, with none of Tailwind's generated-utility,
 * arbitrary-value or built-in escape hatches to allow for.
 */
const LM_PREFIX = "lm-"

/** Strips variants (`hover:`, `min-[820px]:`, `dark:`) and `!` important. */
function bareClass(token: string): string {
  const withoutVariants = token.slice(token.lastIndexOf(":") + 1)
  return withoutVariants.replace(/^!/, "")
}

/**
 * The source with comments removed.
 *
 * Not optional, and the first draft of this gate proved it: several of these
 * files explain in a comment which class they stopped using, and one of those
 * comments names `text-display` in backticks. The literal scanner below
 * matched the backticks and reported the file for a class it had just been
 * corrected to stop using — a gate failing on its own fix note. Same trap
 * `studyNotebookMigration.test.ts` documents, so the same treatment: block
 * comment state tracked across lines, line comments to end of line.
 */
function stripComments(source: string): string {
  let out = ""
  let inBlock = false
  for (const raw of source.split("\n")) {
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
    out += "\n"
  }
  return out
}

function classTokens(source: string): string[] {
  const tokens: string[] = []
  // Every string literal in the file. Class names in this codebase live in
  // `className="…"`, `cn("…", …)` and `cva("…")` alike, so scanning literals
  // catches all three without parsing JSX.
  for (const match of stripComments(source).matchAll(
    /"([^"\n]*)"|'([^'\n]*)'|`([^`\n$]*)`/g,
  )) {
    const literal = match[1] ?? match[2] ?? match[3] ?? ""
    for (const token of literal.split(/\s+/)) {
      if (token !== "") tokens.push(token)
    }
  }
  return tokens
}

describe("design-system utilities resolve", () => {
  const css = read(CSS_PATH)
  const classes = literalClasses(css)
  const vars = declaredVars(css)

  /**
   * A class in one of the four families is legitimate when the stylesheet
   * defines it outright, when a theme variable exists for Tailwind to generate
   * it from, when it is a Tailwind built-in, or when it carries an arbitrary
   * value (`text-[13px]`, `bg-[var(--x)]`) or an opacity modifier
   * (`bg-accent/20`) — those resolve by construction.
   */
  function resolves(withModifier: string): boolean {
    // The `lm-` family is checked before the escape hatches, not after: the
    // project defines these by hand, so an arbitrary value or an opacity
    // modifier on one would itself be a mistake rather than a reason to pass.
    if (withModifier.startsWith(LM_PREFIX)) return classes.has(withModifier)
    if (withModifier.includes("[")) return true
    if (withModifier.includes("(")) return true
    // The opacity modifier is stripped first, not last: `border-current/40` is
    // as legitimate as `border-current`, and checking the built-in list before
    // stripping reported the one and not the other.
    const bare = withModifier.split("/")[0]
    if (BUILT_IN.has(bare)) return true
    // `border-t`, `border-b-2`, `border-0`, `border-x`, `border-s`: the side
    // and width utilities, which are generated from the spacing scale rather
    // than from a colour token and so cannot be looked up as one.
    if (/^border-(?:[trblxyse]-)?\d+$/.test(bare)) return true
    if (/^border-[trblxyse]$/.test(bare)) return true

    const name = bare
    if (classes.has(name)) return true

    const prefix = PREFIXES.find((p) => name.startsWith(p))
    if (prefix === undefined) return true // not ours to judge
    const rest = name.slice(prefix.length)
    if (rest === "") return true // bare `border`, `font`

    if (prefix === "font-") return vars.has(`font-${rest}`)
    // `text-` can be a colour or a size; the others are colours only.
    if (prefix === "text-") {
      return vars.has(`color-${rest}`) || vars.has(`text-${rest}`)
    }
    // `border-s-accent` is a per-side border *colour*, so the side segment is
    // dropped before the token lookup. Only for `border-`: there is no
    // `text-s-…` or `bg-s-…`.
    const colourName =
      prefix === "border-" ? rest.replace(/^[trblxyse]-/, "") : rest
    // The CSS-wide colour keywords survive the side strip too
    // (`border-s-transparent`), so they are checked here rather than only in
    // the whole-class built-in list above.
    if (["transparent", "current", "inherit", "white", "black"].includes(colourName)) {
      return true
    }
    return vars.has(`color-${colourName}`)
  }

  it.each(SCANNED_FILES)("%s names no utility that resolves to nothing", (relative) => {
    const unresolved = new Set<string>()
    for (const token of classTokens(read(relative))) {
      const bare = bareClass(token)
      if (!PREFIXES.some((p) => bare.startsWith(p))) continue
      if (!resolves(bare)) unresolved.add(bare)
    }
    expect([...unresolved].sort()).toEqual([])
  })

  /**
   * Verified by inversion, so the gate is known to fail on the real defect
   * rather than merely known to pass today. `text-display` is the exact string
   * that shipped on four `<h1>`s; `text-not-a-token` stands for the general
   * case.
   */
  it("rejects the class the four page titles actually carried", () => {
    expect(resolves("text-display")).toBe(false)
    expect(resolves("text-not-a-token")).toBe(false)
    expect(resolves("bg-nonexistent")).toBe(false)
    expect(resolves("font-madeup")).toBe(false)
  })

  /**
   * The same inversion for the `lm-` family, on the two strings that actually
   * shipped on the student shell's `<header>` and `<main>`. If this ever goes
   * green while those classes are still undefined, the family check has been
   * disabled and the third recurrence can quietly become a fourth.
   */
  it("rejects the two lm- classes the student shell actually carried", () => {
    expect(resolves("lm-head")).toBe(false)
    expect(resolves("lm-body")).toBe(false)
  })

  it("accepts the lm- classes the stylesheet really defines", () => {
    for (const name of ["lm-read", "lm-prose", "lm-screen", "lm-scroll", "lm-pop"]) {
      expect(resolves(name), name).toBe(true)
    }
  })

  it("accepts the names the design system does define", () => {
    for (const name of [
      "text-display-lg",
      "text-data-md",
      "text-body-sm",
      "text-eyebrow",
      "text-ink-faint",
      "bg-paper-sunk",
      "bg-accent/20",
      "border-rule",
      "font-mono",
      "text-[13px]",
    ]) {
      expect(resolves(name), name).toBe(true)
    }
  })
})
