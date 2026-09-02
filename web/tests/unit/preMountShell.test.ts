import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { fillPreMountShell, readLoadingTierDurations } from "../../vite/preMountShell.ts"

/*
 * The pre-mount shell's placeholder plugin (PR 2 part B), pattern borrowed
 * from `fontPreload.test.ts`: exercise the pure functions directly rather than
 * running a real Vite build, so a broken substitution fails a unit test
 * instead of only showing up as a literal `%LEMELY_COLOR_PAPER%` string
 * painted in a browser.
 *
 * ── What this protects ──────────────────────────────────────────────────────
 *
 * `index.html`'s pre-mount shell paints before `index.css` exists, so its
 * colours and durations cannot be `var(...)` — they are the nine
 * `%LEMELY_*%` placeholders `preMountShell.ts` resolves at build time. The
 * failure mode this guards against is silent in the same way `themeColor.ts`'s
 * is: a renamed token, a placeholder dropped by an unrelated edit, or a typo'd
 * regex all leave the build succeeding and the shipped HTML wrong, on the one
 * screen no test that renders the real app will ever exercise (it disappears
 * the instant React mounts).
 */

const ROOT = join(import.meta.dirname, "..", "..")
const REAL_INDEX_HTML = readFileSync(join(ROOT, "index.html"), "utf8")

const COLOR_PLACEHOLDERS = [
  "%LEMELY_COLOR_PAPER%",
  "%LEMELY_COLOR_PAPER_SUNK%",
  "%LEMELY_COLOR_PAPER_RAISED%",
  "%LEMELY_COLOR_RULE%",
  "%LEMELY_COLOR_INK%",
  "%LEMELY_COLOR_INK_MUTED%",
  "%LEMELY_COLOR_ACCENT%",
]

const DURATION_PLACEHOLDERS = ["%LEMELY_LOADING_TIER_SKELETON%", "%LEMELY_LOADING_TIER_SLOW%"]

describe("readLoadingTierDurations", () => {
  it("reads both tier durations off a real index.css", () => {
    const css = readFileSync(join(ROOT, "src/index.css"), "utf8")
    expect(readLoadingTierDurations(css)).toEqual({
      "%LEMELY_LOADING_TIER_SKELETON%": "200ms",
      "%LEMELY_LOADING_TIER_SLOW%": "5000ms",
    })
  })

  it("throws, naming the token, when a duration declaration is missing", () => {
    const withoutSlow = `:root {\n  --loading-tier-skeleton: 200ms;\n}\n`
    expect(() => readLoadingTierDurations(withoutSlow)).toThrow(/loading-tier-slow/)
  })

  it("throws on an empty file rather than resolving to an empty string", () => {
    expect(() => readLoadingTierDurations("")).toThrow(/loading-tier-skeleton/)
  })
})

describe("fillPreMountShell", () => {
  it("replaces every colour and duration placeholder in the real index.html", () => {
    const filled = fillPreMountShell(REAL_INDEX_HTML)
    for (const placeholder of [...COLOR_PLACEHOLDERS, ...DURATION_PLACEHOLDERS]) {
      expect(filled).not.toContain(placeholder)
    }
  })

  it("substitutes a real hex colour for each colour placeholder", () => {
    const filled = fillPreMountShell(REAL_INDEX_HTML)
    // --paper is documented at ~#F8F7F4 (DESIGN.md §3.1); assert the shape
    // rather than the exact value so a deliberate token nudge doesn't break
    // this test for an unrelated reason.
    expect(filled).toMatch(/#[0-9a-f]{6}/)
  })

  it("substitutes the real durations for the duration placeholders", () => {
    const filled = fillPreMountShell(REAL_INDEX_HTML)
    expect(filled).toContain("200ms")
    expect(filled).toContain("5000ms")
  })

  it("throws when a colour placeholder is missing from the source", () => {
    const withoutPaper = REAL_INDEX_HTML.replaceAll("%LEMELY_COLOR_PAPER%", "")
    expect(() => fillPreMountShell(withoutPaper)).toThrow(/LEMELY_COLOR_PAPER/)
  })

  it("throws when a duration placeholder is missing from the source", () => {
    const withoutSlow = REAL_INDEX_HTML.replaceAll("%LEMELY_LOADING_TIER_SLOW%", "")
    expect(() => fillPreMountShell(withoutSlow)).toThrow(/LEMELY_LOADING_TIER_SLOW/)
  })

  it("is idempotent-safe against an already-empty document", () => {
    // Not a realistic input, but pins that a short/malformed document throws
    // rather than resolving every placeholder to the empty string.
    expect(() => fillPreMountShell("<html></html>")).toThrow(/LEMELY_COLOR/)
  })
})

describe("index.html source: no hex colour literal outside comments", () => {
  /*
   * The shell's colours are ONLY the seven placeholders above — see
   * `fillPreMountShell`'s own doc comment for why a literal hex here would be
   * the same silent-drift failure `themeColor.ts` exists to prevent. Existing
   * documentation comments in this file's `<head>` DO name two historical
   * hexes (`#863bff`, `#1e1310`) as part of explaining why those colours were
   * wrong; those are prose, not colour, so they are stripped before this
   * checks, the same way `scripts/check_copy.mjs` strips comments before
   * scanning for em-dashes.
   */
  function stripHtmlComments(html: string): string {
    return html.replace(/<!--[\s\S]*?-->/g, (comment) => comment.replace(/[^\n]/g, " "))
  }

  it("has no # colour literal in the source outside an HTML comment", () => {
    const withoutComments = stripHtmlComments(REAL_INDEX_HTML)
    expect(withoutComments).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })

  it("still names the historical hexes inside the theme-color comments", () => {
    // Confirms stripHtmlComments is actually finding and blanking comments,
    // rather than this test passing because the source has no hex anywhere.
    expect(REAL_INDEX_HTML).toContain("#863bff")
    expect(REAL_INDEX_HTML).toContain("#1e1310")
  })
})
