import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { relativeTo, sourceFiles, stripComments } from "./support/jsxSource"

/*
 * L10 Task 16 · fidelity drift that no render-free test sees.
 *
 * Three rules in `src/index.css` are unlayered, so they beat every Tailwind utility (which is layered)
 * whatever the value. Each one quietly undid a flashcards design value, and each looked right in a
 * source review:
 *
 *   - `@media (pointer: coarse) { button, [role="button"] { min-block-size: 44px } }` capped every
 *     `min-h-[50px]` and `min-h-[62px]` control at 44px on a phone. The mock's buttons are 54px and the
 *     grade buttons 62px. Only `!min-h-[Npx]` (important) wins.
 *   - `:focus-visible { border-radius: 2px }` took the 28px review card down to a 2px corner the moment a
 *     keyboard user pressed Space. `focus-visible:rounded-[28px]` could never win; `focus-visible:!rounded-[28px]` does.
 *   - The shell's native frame already draws the page title as a large title, so a screen heading that
 *     repeats it must be `PageHeading repeatsTitle` (`native:sr-only`), never a bare `<h1>`.
 */

const SCREENS = join(process.cwd(), "src/portals/student/screens/flashcards")
const files = sourceFiles(SCREENS).map((file) => ({
  name: relativeTo(process.cwd(), file),
  source: stripComments(readFileSync(file, "utf8")),
}))

describe("flashcards fidelity guards", () => {
  it("every control floor above the 44px touch floor is important, or the touch rule caps it", () => {
    const capped: string[] = []
    for (const { name, source } of files) {
      for (const m of source.matchAll(/(!?)min-h-\[(\d+)px\]/g)) {
        const px = Number(m[2])
        // 45..99 is a control height. Larger values are container floors (the 320px card stage).
        if (px > 44 && px < 100 && m[1] !== "!") capped.push(`${name}: min-h-[${px}px]`)
      }
    }
    expect(capped).toEqual([])
  })

  // Per-component only. index.css has an unlayered `:focus-visible { border-radius: 2px }` that squares any
  // rounded control's ring, and this lane patches just the two places it set a radius itself (DeckRow, ReviewCard).
  // A flashcards control with no radius utility is still squared by it; that is the shell's to fix once, not
  // here. What this proves: where this lane DOES write `focus-visible:rounded-[Npx]`, it is `!`-important.
  it("a focus radius this lane writes is important, or the global :focus-visible 2px radius wins", () => {
    const squared: string[] = []
    for (const { name, source } of files) {
      for (const m of source.matchAll(/focus-visible:(!?)rounded-\[\d+px\]/g)) {
        if (m[1] !== "!") squared.push(`${name}: ${m[0]}`)
      }
    }
    expect(squared).toEqual([])
  })

  it("the solid 54px action button is defined once, in parts/buttonStyles.ts, and every screen uses it", () => {
    const copies = files.filter((f) => /rounded-\[18px\][^"`']*\bbg-(primary|on-error-container)\b/.test(f.source)).map((f) => f.name)
    expect(copies).toEqual([])
    const styles = readFileSync(join(SCREENS, "parts/buttonStyles.ts"), "utf8")
    expect(styles).toContain("!min-h-[54px]")
    expect(styles).toContain("shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)]")
    expect(styles).toContain("disabled:shadow-none")
  })

  it("leading-tight sits on text stacks, never on a screen root or a paragraph", () => {
    const stray: string[] = []
    for (const { name, source } of files) {
      for (const m of source.matchAll(/<p\b[^>]*leading-tight/g)) stray.push(`${name}: ${m[0].slice(0, 60)}`)
      for (const m of source.matchAll(/max-w-\[640px\][^"`]*leading-tight|pb-24 pt-3\.5 leading-tight|grid gap-3 leading-tight/g)) stray.push(`${name}: ${m[0]}`)
    }
    expect(stray).toEqual([])
  })

  it("the done-screen wash uses shell gutters on web, iOS and Android", () => {
    const done = files.find((f) => f.name.endsWith("flashcards/ReviewDone.tsx"))
    expect(done?.source).toContain("fc-review-done")
    expect(done?.source).toContain("-ml-[var(--fc-bleed-l)]")
    expect(done?.source).toContain("-mr-[var(--fc-bleed-r)]")
    const css = readFileSync(join(SCREENS, "flashcards.css"), "utf8")
    expect(css).toContain("--fc-bleed-l: var(--native-bleed-l, 14px)")
    expect(css).toContain("--fc-bleed-r: var(--native-bleed-r, 14px)")
    expect(css).toContain(':root[data-platform="ios"] .fc-review-done')
    expect(css).toContain("max(var(--native-group-inset-ios), env(safe-area-inset-left))")
    expect(css).toContain("max(var(--native-group-inset-ios), env(safe-area-inset-right))")
  })

  it("both review screens fill the viewport above the bottom bar the platform shows, from one shared variable", () => {
    for (const name of ["ReviewScreen.tsx", "ReviewDone.tsx"]) {
      const file = files.find((f) => f.name.endsWith(`/${name}`))
      expect(file?.source, name).toContain("fc-review-fill")
      expect(file?.source, name).toContain("min-h-[var(--fc-review-min-h)]")
      // The old per-screen copies subtracted only the native tab bar, so plain web ran under the bottom nav.
      expect(file?.source, name).not.toMatch(/(?<![:\w-])min-h-\[calc\(100dvh/)
    }
    const css = readFileSync(join(SCREENS, "flashcards.css"), "utf8")
    const fill = css.match(/\.fc-review-fill \{[^}]*\}/)?.[0] ?? ""
    expect(fill).toContain("--fc-nav-h: var(--native-tabbar-h, calc(var(--bottom-nav-height, 56px) + 7px))")
    expect(fill).toContain("- var(--fc-nav-h)")
    expect(fill).toContain("- var(--fc-top-extra)")
    expect(css).toMatch(/@media \(min-width: 820px\) \{\s*\.fc-review-fill \{\s*--fc-nav-h: 0px/)
  })

  it("every error alert box takes its look from parts/errorAlert.ts, never a copy of the classes", () => {
    const copies: string[] = []
    for (const { name, source } of files) {
      if (name.endsWith("parts/errorAlert.ts")) continue
      if (/bg-error-container[^"`']*px-3 py-2\.5|px-3 py-2\.5[^"`']*bg-error-container/.test(source)) copies.push(name)
      for (const m of source.matchAll(/role="alert"[^>]*className=("[^"]*"|\{[^}]*\})/g)) {
        if (!m[1].includes("ERROR_ALERT") && m[1].includes("error-container")) copies.push(`${name}: ${m[1].slice(0, 50)}`)
      }
    }
    expect(copies).toEqual([])
    expect(readFileSync(join(SCREENS, "parts/errorAlert.ts"), "utf8")).toContain("leading-tight")
  })

  it("the shelf heading is a PageHeading that repeats the shell title, not a bare h1", () => {
    const shelf = files.find((f) => f.name.endsWith("flashcards/FlashcardsScreen.tsx"))
    expect(shelf).toBeDefined()
    expect(shelf!.source).toMatch(/<PageHeading repeatsTitle[^>]*data-fc-heading/)
    expect(shelf!.source).not.toMatch(/<h1[\s>]/)
  })

  it("the unlayered rules these guards answer to are still in index.css", () => {
    const css = readFileSync(join(process.cwd(), "src/index.css"), "utf8")
    expect(css).toMatch(/@media \(pointer: coarse\)[\s\S]{0,400}min-block-size: 44px/)
    expect(css).toMatch(/:focus-visible \{[^}]*border-radius: 2px/)
  })
})
