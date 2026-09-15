import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * C4 (Task 11): the print stylesheet, `web/src/index.css`'s `@media print`
 * block. Source-text assertions only — this repo's vitest runner is
 * `environment: "node"` (D3.20), no jsdom, so a real cascade/media-query
 * evaluation is out of reach here; that behaviour is Playwright's job.
 *
 * These tests pin the rules a printed portal screen depends on:
 *   - `[data-print="hide"]` collapses chrome the print block does not own
 *     the removal of (that removal itself lives in the components that carry
 *     the attribute; this only pins that the selector exists and hides).
 *   - `.lm-print-avoid-break` keeps a question block from splitting across a
 *     page boundary.
 *   - the paper surface is forced to white for print regardless of the
 *     on-screen theme (dark mode, a later task, must never bleed onto paper).
 */

const ROOT = join(import.meta.dirname, "..", "..")
const read = (p: string) => readFileSync(join(ROOT, p), "utf8")

describe("the @media print block", () => {
  const css = read("src/index.css")
  const printBlockMatch = css.match(/@media print \{([\s\S]*?)\n\}/)

  it("exists", () => {
    expect(printBlockMatch).not.toBeNull()
  })

  const printBlock = printBlockMatch?.[1] ?? ""

  it("hides any element carrying data-print=\"hide\"", () => {
    expect(printBlock).toMatch(/\[data-print="hide"\]\s*\{[^}]*display:\s*none\s*!important/)
  })

  it("keeps a print-avoid-break block from splitting across a page", () => {
    expect(printBlock).toMatch(/\.lm-print-avoid-break\s*\{[^}]*break-inside:\s*avoid/)
    // Vendor fallback for engines that only understand the legacy property.
    expect(printBlock).toMatch(/\.lm-print-avoid-break\s*\{[^}]*page-break-inside:\s*avoid/)
  })

  it("forces the paper surface to white, independent of the on-screen theme", () => {
    expect(printBlock).toMatch(/--paper:\s*#fff/)
    expect(printBlock).toMatch(/--paper-raised:\s*#fff/)
    expect(printBlock).toMatch(/--paper-sunk:\s*#fff/)
  })

  /*
   * C4/C5 review fix: `@media` adds no specificity, so a bare `:root`
   * (0,1,0) loses the cascade to the dark ladder's `:root[data-theme="dark"]`
   * (0,2,0) regardless of source order — printing while the theme preference
   * was dark left the print surface on the dark paper/ink pair unchanged
   * (near-white ink on white paper, since browsers don't print backgrounds
   * by default). The override must also match `:root[data-theme="dark"]`
   * directly, at the same specificity the dark ladder itself uses.
   */
  it("also targets :root[data-theme=\"dark\"] directly, at the same specificity the dark ladder uses", () => {
    expect(printBlock).toMatch(/:root\[data-theme="dark"\]/)
  })

  /*
   * Specificity alone is not enough: the pre-fix block reset only
   * `--paper*`, never `--ink*` — so even where the override DID apply, dark
   * mode's near-white `--ink` would have survived onto the printed page.
   * This asserts the `:root` and `:root[data-theme="dark"]` selectors reset
   * an EQUIVALENT set of custom properties (not just that the dark selector
   * exists), so a future edit that adds a new `--paper-*`/`--ink-*` variant
   * to one but not the other fails here rather than shipping silently.
   */
  it("resets the same custom properties for :root and :root[data-theme=\"dark\"]", () => {
    // Split the print block into its top-level `selector { body }` rules.
    const rules = [...printBlock.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selector, body]) => ({
      selector,
      props: [...body.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]).sort(),
    }))

    const lightRootRules = rules.filter((r) => /(^|[\s,])\.?:root(?!\[)/.test(r.selector))
    const darkRootRules = rules.filter((r) => /:root\[data-theme="dark"\]/.test(r.selector))

    expect(lightRootRules.length).toBeGreaterThan(0)
    expect(darkRootRules.length).toBeGreaterThan(0)

    const lightProps = [...new Set(lightRootRules.flatMap((r) => r.props))].sort()
    const darkProps = [...new Set(darkRootRules.flatMap((r) => r.props))].sort()

    // At minimum, the paper, ink AND semantic (ok/warn/err) triples travel
    // together — PaperResult.tsx's IntegrityMark and "Needs review" copy
    // print in --ok/--warn, unhidden by data-print="hide", and re-verification
    // review found they washed out under the same specificity bug (dark
    // --warn measured 2.10:1 on forced white paper vs light's 7.58:1).
    expect(lightProps).toEqual(expect.arrayContaining(["--paper", "--paper-raised", "--paper-sunk"]))
    expect(lightProps).toEqual(expect.arrayContaining(["--ink", "--ink-muted", "--ink-faint"]))
    expect(lightProps).toEqual(expect.arrayContaining(["--ok", "--warn", "--err"]))
    expect(darkProps).toEqual(lightProps)
  })

  /*
   * §14 rule 3: tokens only, no arbitrary literals — except the one place
   * this file's own comment calls out as the allowed exception, the print
   * override itself. A declaration assigning `#fff` anywhere else in
   * index.css would be an unreviewed literal smuggled past that rule.
   *
   * Scoped to `: #fff` (an actual declared value), not a bare substring
   * match — this file also has a *prose* comment ("Never pure #FFF") that
   * legitimately names the literal without declaring it.
   */
  it("is the only place index.css declares #fff as a value", () => {
    const withoutPrintBlock = css.replace(/@media print \{[\s\S]*?\n\}/, "")
    expect(withoutPrintBlock).not.toMatch(/:\s*#fff\b/i)
  })
})

describe("question-row.tsx", () => {
  it("carries the print-avoid-break class on its root", () => {
    const src = read("src/components/ui/question-row.tsx")
    expect(src).toMatch(/lm-print-avoid-break/)
  })
})

describe("PaperResult.tsx", () => {
  it("hides the Share action from print — an on-screen affordance with no printed target", () => {
    const src = read("src/portals/student/screens/PaperResult.tsx")
    const shareButtonStart = src.indexOf("<Button")
    expect(shareButtonStart).toBeGreaterThan(-1)
    const shareButtonTag = src.slice(shareButtonStart, src.indexOf(">", shareButtonStart))
    expect(shareButtonTag).toMatch(/data-print="hide"/)
  })
})
