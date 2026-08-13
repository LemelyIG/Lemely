import { readdirSync, readFileSync } from "node:fs"
import { join, relative } from "node:path"
import { describe, expect, it } from "vitest"

/** Every `.ts`/`.tsx` file under a directory, recursively. */
function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(full)
    return /\.tsx?$/.test(entry.name) ? [full] : []
  })
}

/**
 * The banned-easing gate.
 *
 * P4.6 found that DESIGN.md §3.2 item 14 — "never `linear` or `ease-in-out` on
 * a designed transition" — was being violated by *every* transition in the
 * product, and by none of them explicitly.
 *
 * Tailwind ships two defaults:
 *
 *     --default-transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1)
 *     --default-transition-duration: 150ms
 *
 * and every `transition-colors` / `transition-transform` utility resolves
 * through `var(--tw-ease, var(--default-transition-timing-function))`. A call
 * site that names no easing therefore silently gets the symmetric ease-in-out
 * curve. There were 27 such call sites across the migrated surfaces plus the
 * whole component kit, and not one of them wrote a banned class name, so no
 * grep for `ease-in-out` could ever have found this.
 *
 * It is the same shape as D4.1's `--font-serif` (a well-formed utility
 * resolving to somebody else's default) with one difference that matters:
 * `font-serif` resolved to *nothing we defined*, so `utilityExistence.test.ts`
 * can see it. These classes do emit rules. They emit the wrong ones, which is
 * invisible to every gate that asks whether a class exists.
 *
 * So this checks the value rather than the name, in both directions:
 * the defaults must point at a §9.1 easing, and no source file may reach for a
 * banned one explicitly.
 */

/**
 * Source with `/* … *​/` comments blanked out.
 *
 * Not optional, and the first run of this gate proved why in both directions:
 * the CSS comment introducing the fix quotes Tailwind's `150ms` default, so
 * the duration check read the comment instead of the declaration; and
 * `button.tsx` writes "never `ease-in-out` or `linear`" *inside* a `cva(` call,
 * so the banned-easing check reported the file that documents the rule. A gate
 * that reads prose as code punishes the explanation, which is the same call
 * `studyNotebookMigration.test.ts` had to make.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, "")
}

const CSS = stripComments(readFileSync(join(process.cwd(), "src/index.css"), "utf8"))

/** The four easings §9.1 defines. Anything else is not a designed easing. */
const DESIGNED_EASINGS = ["ease-out-soft", "ease-in-soft", "ease-spring", "ease-celebrate"]

function declaration(name: string): string | null {
  const match = CSS.match(new RegExp(`--${name}\\s*:\\s*([^;]+);`))
  return match ? match[1].trim() : null
}

describe("motion defaults (DESIGN.md §9.1, §3.2 item 14)", () => {
  it("the default transition easing is one of the four designed easings", () => {
    const value = declaration("default-transition-timing-function")
    expect(value).not.toBeNull()
    expect(
      DESIGNED_EASINGS.some((name) => value?.includes(`var(--${name})`)),
      `--default-transition-timing-function is "${value}", which is not one of ${DESIGNED_EASINGS.join(", ")}`,
    ).toBe(true)
  })

  it("the default transition easing is not a raw cubic-bezier or a CSS keyword", () => {
    const value = declaration("default-transition-timing-function") ?? ""
    // Tailwind's own default is a literal `cubic-bezier(0.4, 0, 0.2, 1)`. If
    // this line ever stops being a `var()` reference, the easing has been
    // pinned at a call site instead of taken from the token block, which is
    // the §3.2 item 13 failure as well as this one.
    expect(value).toMatch(/^var\(--ease-/)
    expect(value).not.toMatch(/\b(linear|ease-in-out|ease-in|ease-out|ease)\s*$/)
  })

  it("the default transition duration is one of the §9.1 durations", () => {
    const value = declaration("default-transition-duration")
    expect(value).not.toBeNull()
    // §9.1: instant 120, fast 200, base 320, slow 600, celebrate 900. A bare
    // transition is a hover colour, so `dur-instant` is the right default; the
    // assertion is deliberately the whole set rather than the one value, since
    // moving it to `dur-fast` would be a design decision and not a defect.
    expect(["120ms", "200ms", "320ms", "600ms", "900ms"]).toContain(value)
  })

  /**
   * Inversion. The first two tests would also pass against a stylesheet that
   * simply never declared the defaults (`toBeNull` would fail first, which is
   * why it is asserted) — but they would NOT catch a call site that writes the
   * banned easing by hand, so that is checked separately below.
   */
  it("the stylesheet defines all four §9.1 easings for the defaults to point at", () => {
    for (const name of DESIGNED_EASINGS) {
      expect(CSS, `--${name} is missing from index.css`).toContain(`--${name}:`)
    }
  })

  /**
   * Every `className` string in `src`, so the two checks below judge real class
   * tokens rather than the prose in a comment. Three files legitimately *name*
   * `ease-in-out` while explaining why they do not use it, and a gate that
   * punished the explanation would delete the commentary a later reader needs.
   */
  const classNames: { file: string; value: string }[] = []
  for (const file of sourceFiles(join(process.cwd(), "src"))) {
    const source = stripComments(readFileSync(file, "utf8"))
    for (const match of source.matchAll(/className\s*=\s*(?:"([^"]*)"|\{`([^`]*)`\}|\{"([^"]*)"\})/g)) {
      classNames.push({
        file: relative(process.cwd(), file),
        value: match[1] ?? match[2] ?? match[3] ?? "",
      })
    }
    // `cva(...)` and `cn(...)` argument strings are class lists too, and the
    // component kit writes most of its variants there rather than in JSX.
    for (const match of source.matchAll(/(?:cva|cn)\(([\s\S]{0,2000}?)\)/g)) {
      classNames.push({ file: relative(process.cwd(), file), value: match[1] })
    }
  }

  const BANNED_EASING_CLASSES = ["ease-linear", "ease-in-out", "ease-initial"]

  it("no className reaches for a banned easing", () => {
    const offences = classNames
      .filter(({ value }) =>
        BANNED_EASING_CLASSES.some((banned) =>
          new RegExp(`(?<![\\w-])(?:[a-z-]+:)?${banned}(?![\\w-])`).test(value),
        ),
      )
      .map(({ file }) => file)

    expect([...new Set(offences)]).toEqual([])
  })

  /**
   * `duration-<name>` does not exist in this theme, and writing one is how the
   * resolves-to-nothing defect gets in through the motion door.
   *
   * The `--dur-*` tokens live in `:root`, not in `@theme`, so Tailwind
   * generates no utility from them: `duration-instant` is a well-formed class
   * that emits no rule, exactly like `text-display` (D4.4) and `lm-head`
   * (D4.5). This was caught while writing this surface, before it shipped, by
   * checking rather than assuming. Numeric (`duration-200`) and arbitrary
   * (`duration-[120ms]`) forms are real Tailwind and stay allowed — though the
   * corrected default above means most call sites need neither.
   */
  it("no className uses a named duration utility, which would resolve to nothing", () => {
    const offences = classNames
      .filter(({ value }) => /(?<![\w-])(?:[a-z-]+:)?duration-(?![\d[])[a-z]/.test(value))
      .map(({ file }) => file)

    expect([...new Set(offences)]).toEqual([])
  })
})
