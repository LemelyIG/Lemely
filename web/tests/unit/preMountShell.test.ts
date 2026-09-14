import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { fillPreMountShell, readLoadingTierDurations, readSidebarTokens } from "../../vite/preMountShell.ts"
import { FULL_PAGE_STATE_COPY } from "../../src/portals/misc/fullPageStateCopy.ts"

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

// Task 13 (C5b): the dark counterpart of every COLOR_PLACEHOLDERS entry
// except %LEMELY_COLOR_ACCENT% (which, per that entry's own comment above,
// was never a real placeholder in index.html to begin with).
const COLOR_PLACEHOLDERS_DARK = [
  "%LEMELY_COLOR_DARK_PAPER%",
  "%LEMELY_COLOR_DARK_PAPER_SUNK%",
  "%LEMELY_COLOR_DARK_PAPER_RAISED%",
  "%LEMELY_COLOR_DARK_RULE%",
  "%LEMELY_COLOR_DARK_INK%",
  "%LEMELY_COLOR_DARK_INK_MUTED%",
]

const DURATION_PLACEHOLDERS = ["%LEMELY_LOADING_TIER_SKELETON%", "%LEMELY_LOADING_TIER_SLOW%"]

// Packet B3 (Task 4): the sidebar width/breakpoint literals index.html's
// pre-mount shell used to hardcode (246px, 820px) are now resolved from
// index.css's `--sidebar-width`/`--breakpoint-sidebar` tokens the same way
// the two duration placeholders above are — see `readSidebarTokens`.
const SIZE_PLACEHOLDERS = ["%LEMELY_SIDEBAR_WIDTH%", "%LEMELY_SIDEBAR_BREAKPOINT%"]

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

describe("readSidebarTokens", () => {
  it("reads both size tokens off a real index.css", () => {
    const css = readFileSync(join(ROOT, "src/index.css"), "utf8")
    expect(readSidebarTokens(css)).toEqual({
      "%LEMELY_SIDEBAR_WIDTH%": "252px",
      "%LEMELY_SIDEBAR_BREAKPOINT%": "820px",
    })
  })

  it("throws, naming the token, when a declaration is missing", () => {
    const withoutWidth = `:root {\n  --breakpoint-sidebar: 820px;\n}\n`
    expect(() => readSidebarTokens(withoutWidth)).toThrow(/sidebar-width/)
  })

  it("throws on an empty file rather than resolving to an empty string", () => {
    expect(() => readSidebarTokens("")).toThrow(/sidebar-width/)
  })
})

describe("fillPreMountShell", () => {
  it("replaces every colour, duration and size placeholder in the real index.html", () => {
    const filled = fillPreMountShell(REAL_INDEX_HTML)
    for (const placeholder of [
      ...COLOR_PLACEHOLDERS,
      ...COLOR_PLACEHOLDERS_DARK,
      ...DURATION_PLACEHOLDERS,
      ...SIZE_PLACEHOLDERS,
    ]) {
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

  it("substitutes a distinct real hex colour for each dark colour placeholder (Task 13, C5b)", () => {
    // Resolve `[data-theme="dark"] #root { ... }`'s own dark paper directly,
    // rather than just asserting "some hex exists" — that would also pass
    // if this override block resolved to the LIGHT paper by mistake.
    const filled = fillPreMountShell(REAL_INDEX_HTML)
    const darkPaperMatch = filled.match(/\[data-theme="dark"\][^{]*\{\s*background:\s*(#[0-9a-f]{6})/)
    const lightPaperMatch = filled.match(/#root\s*\{\s*background:\s*(#[0-9a-f]{6})/)
    expect(darkPaperMatch?.[1]).toBeDefined()
    expect(lightPaperMatch?.[1]).toBeDefined()
    expect(darkPaperMatch![1]).not.toBe(lightPaperMatch![1])
  })

  it("substitutes the real durations for the duration placeholders", () => {
    const filled = fillPreMountShell(REAL_INDEX_HTML)
    expect(filled).toContain("200ms")
    expect(filled).toContain("5000ms")
  })

  it("substitutes the real sidebar width and breakpoint for the size placeholders", () => {
    const filled = fillPreMountShell(REAL_INDEX_HTML)
    expect(filled).toContain("252px")
    expect(filled).toContain("820px")
  })

  it("throws when a colour placeholder is missing from the source", () => {
    const withoutPaper = REAL_INDEX_HTML.replaceAll("%LEMELY_COLOR_PAPER%", "")
    expect(() => fillPreMountShell(withoutPaper)).toThrow(/LEMELY_COLOR_PAPER/)
  })

  it("throws when a dark colour placeholder is missing from the source (Task 13, C5b)", () => {
    const withoutDarkPaper = REAL_INDEX_HTML.replaceAll("%LEMELY_COLOR_DARK_PAPER%", "")
    expect(() => fillPreMountShell(withoutDarkPaper)).toThrow(/LEMELY_COLOR_DARK_PAPER/)
  })

  it("throws when a duration placeholder is missing from the source", () => {
    const withoutSlow = REAL_INDEX_HTML.replaceAll("%LEMELY_LOADING_TIER_SLOW%", "")
    expect(() => fillPreMountShell(withoutSlow)).toThrow(/LEMELY_LOADING_TIER_SLOW/)
  })

  it("throws when a size placeholder is missing from the source", () => {
    const withoutWidth = REAL_INDEX_HTML.replaceAll("%LEMELY_SIDEBAR_WIDTH%", "")
    expect(() => fillPreMountShell(withoutWidth)).toThrow(/LEMELY_SIDEBAR_WIDTH/)
  })

  it("is idempotent-safe against an already-empty document", () => {
    // Not a realistic input, but pins that a short/malformed document throws
    // rather than resolving every placeholder to the empty string.
    expect(() => fillPreMountShell("<html></html>")).toThrow(/LEMELY_COLOR/)
  })

  it("throws, naming it, on a new %LEMELY_..._% placeholder with no map entry", () => {
    // A placeholder shaped like the nine this plugin knows about, but not one
    // of them: nothing in COLOR_PLACEHOLDERS/DURATION_PLACEHOLDERS would ever
    // report it missing (there is no per-placeholder presence check for a
    // name the maps don't contain), so only the trailing "no leftovers"
    // sweep in fillPreMountShell can catch it.
    const withStray = REAL_INDEX_HTML.replace(
      "%LEMELY_COLOR_PAPER%",
      "%LEMELY_COLOR_PAPER% %LEMELY_COLOR_SURPRISE%",
    )
    expect(() => fillPreMountShell(withStray)).toThrow(/LEMELY_COLOR_SURPRISE/)
  })

  it("leaves no %LEMELY_COLOR_...%, %LEMELY_LOADING_TIER_...% or %LEMELY_SIDEBAR_...% placeholder in the resolved real index.html", () => {
    // Scoped to this plugin's three placeholder families, not every
    // `%LEMELY_..._%` in the document: `%LEMELY_THEME_COLOR%`/
    // `%LEMELY_THEME_COLOR_DARK%` on the `theme-color` meta tag belong to
    // `themeColor.ts`'s own plugin and are never touched by
    // `fillPreMountShell` alone, so both are expected to still be present
    // here.
    const filled = fillPreMountShell(REAL_INDEX_HTML)
    expect(filled).not.toMatch(/%LEMELY_(?:COLOR|LOADING_TIER|SIDEBAR)_[A-Z_]+%/)
    expect(filled).toContain("%LEMELY_THEME_COLOR%")
    expect(filled).toContain("%LEMELY_THEME_COLOR_DARK%")
  })

  it("throws, naming it, on a new %LEMELY_COLOR_DARK_..._% placeholder with no map entry", () => {
    // Mirror of the %LEMELY_COLOR_SURPRISE% case above, for the dark family
    // specifically — pins that COLOR_PLACEHOLDERS_DARK's own leftover sweep
    // (piggybacking on the shared COLOR-prefix branch of the regex) actually
    // catches an unmapped dark placeholder rather than silently shipping it.
    const withStray = REAL_INDEX_HTML.replace(
      "%LEMELY_COLOR_DARK_PAPER%",
      "%LEMELY_COLOR_DARK_PAPER% %LEMELY_COLOR_DARK_SURPRISE%",
    )
    expect(() => fillPreMountShell(withStray)).toThrow(/LEMELY_COLOR_DARK_SURPRISE/)
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

/*
 * Adversarial-review BLOCKER 1: tier 2/tier 3 were hidden from sighted readers
 * by `opacity: 0` alone, which removes nothing from the accessibility tree or
 * the tab order. Both blocks sit inside `<div class="lm-shell" role="status">`,
 * so a screen reader announced tier 3's "Still loading… Reload the page,
 * button" on every cold load, and the reload button was a real, invisible,
 * tabbable stop for the first `%LEMELY_LOADING_TIER_SLOW%` of every visit.
 * The fix rides `visibility` on the same zero-duration/delay animation that
 * already staged `opacity`, since `visibility` is a discrete (non-tweened)
 * property and animating it is a step, not motion — it does not add a second
 * animated property under DESIGN.md §9.2's "transform and opacity only" rule.
 */
describe("BLOCKER 1: tier 2/3 are visibility:hidden until their delay elapses", () => {
  it("lm-shell-appear keyframe starts visibility:hidden and ends visibility:visible", () => {
    const start = REAL_INDEX_HTML.indexOf("@keyframes lm-shell-appear")
    expect(start).toBeGreaterThan(-1)
    const end = REAL_INDEX_HTML.indexOf("}", REAL_INDEX_HTML.indexOf("}", start) + 1)
    const block = REAL_INDEX_HTML.slice(start, end + 1)
    expect(block).toMatch(/from\s*\{[^}]*visibility:\s*hidden/)
    expect(block).toMatch(/to\s*\{[^}]*visibility:\s*visible/)
  })

  it(".lm-shell-tier2 and .lm-shell-tier3 both set visibility:hidden as their pre-animation state", () => {
    // Each selector also appears in an earlier COMBINED rule
    // (`.lm-shell-tier2,\n.lm-shell-tier3 { grid-column: 1; ... }`) that has
    // nothing to do with the staging animation, so a plain "find the next
    // `}`" from the first occurrence of the selector lands on the wrong
    // block. Matching the whole `selector { ... }` rule and filtering for
    // the one that actually carries `animation: lm-shell-appear` finds the
    // right one regardless of how many other rules share the selector name.
    for (const selector of [".lm-shell-tier2", ".lm-shell-tier3"]) {
      const pattern = new RegExp(
        `${selector.replace(".", "\\.")}\\s*\\{[^}]*\\}`,
        "g",
      )
      const blocks = REAL_INDEX_HTML.match(pattern) ?? []
      const stagingRule = blocks.find((block) => block.includes("animation: lm-shell-appear"))
      expect(stagingRule, `${selector}'s staging rule (with animation: lm-shell-appear) not found`).toBeDefined()
      expect(stagingRule).toMatch(/visibility:\s*hidden/)
    }
  })

  it("index.css's lm-appear keyframe and tier classes carry the same fix", () => {
    const css = readFileSync(join(ROOT, "src/index.css"), "utf8")
    const start = css.indexOf("@keyframes lm-appear")
    expect(start).toBeGreaterThan(-1)
    const end = css.indexOf("}", css.indexOf("}", start) + 1)
    const block = css.slice(start, end + 1)
    expect(block).toMatch(/from\s*\{[^}]*visibility:\s*hidden/)
    expect(block).toMatch(/to\s*\{[^}]*visibility:\s*visible/)

    for (const cls of [".lm-tier-skeleton", ".lm-tier-slow"]) {
      const ruleStart = css.indexOf(`${cls} {`)
      expect(ruleStart, `${cls} rule not found`).toBeGreaterThan(-1)
      const ruleEnd = css.indexOf("}", ruleStart)
      const rule = css.slice(ruleStart, ruleEnd)
      expect(rule).toMatch(/visibility:\s*hidden/)
    }
  })
})

/*
 * Adversarial-review BLOCKER 2: the pre-mount shell's portal chrome had no
 * mobile breakpoint — a fixed sidebar column and a matching `margin-left`
 * inset on tier 3 painted unconditionally, while the real portal `<aside>`
 * only exists from the `sidebar:` breakpoint up
 * (`src/portals/student/index.tsx`). Pinned as a source-text assertion: the
 * two `%LEMELY_SIDEBAR_WIDTH%` declarations may only appear inside a
 * `min-width: %LEMELY_SIDEBAR_BREAKPOINT%` media query.
 *
 * Packet B3 (Task 4) moved the two gated values off literal `246px`/`820px`
 * onto `%LEMELY_SIDEBAR_WIDTH%`/`%LEMELY_SIDEBAR_BREAKPOINT%`, resolved from
 * the same `--sidebar-width`/`--breakpoint-sidebar` tokens `nav-shells.tsx`'s
 * `SIDEBAR_WIDTH`/`SIDEBAR_BREAKPOINT` constants read — see
 * `readSidebarTokens` above. This block now asserts the gating on the
 * placeholder (pre-build) and, separately, on the resolved 252px/820px
 * values `fillPreMountShell` produces (post-build) — the two-value drift
 * this test caught with a bare literal is impossible now (both come from one
 * token pair), but the "still gated on the real breakpoint" property is
 * unrelated to that and still worth pinning on the actual shipped markup.
 */
describe("BLOCKER 2: the sidebar column/inset are gated on the sidebar breakpoint", () => {
  function assertGated(html: string, valuePattern: RegExp, mediaQuery: string, label: string) {
    const styleStart = html.indexOf("<style>")
    const styleEnd = html.indexOf("</style>")
    const style = html.slice(styleStart, styleEnd)

    // Declarations only: the value inside a CSS comment (prose explaining the
    // rule) doesn't count, so comments are blanked the same way
    // stripHtmlComments (above) blanks HTML comments.
    const withoutComments = style.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, " "))

    const declarations = [...withoutComments.matchAll(valuePattern)]
    expect(declarations.length, `no ${label} declaration found at all`).toBeGreaterThan(0)

    for (const match of declarations) {
      const before = withoutComments.slice(0, match.index)
      const lastMediaOpen = before.lastIndexOf(mediaQuery)
      // Every "{" between the media query and this match, minus every "}",
      // must stay net positive — i.e. the match is still nested inside that
      // media query's braces, not in a sibling rule after it closed.
      expect(lastMediaOpen, `${label} declaration found outside any ${mediaQuery} media query`).toBeGreaterThan(-1)
      const between = before.slice(lastMediaOpen)
      const depth = (between.match(/\{/g) ?? []).length - (between.match(/\}/g) ?? []).length
      expect(depth, `${label} declaration found after its enclosing @media block closed`).toBeGreaterThan(0)
    }
  }

  it("every %LEMELY_SIDEBAR_WIDTH% declaration in the source sits inside a min-width: %LEMELY_SIDEBAR_BREAKPOINT% media query", () => {
    assertGated(
      REAL_INDEX_HTML,
      /%LEMELY_SIDEBAR_WIDTH%/g,
      "@media (min-width: %LEMELY_SIDEBAR_BREAKPOINT%)",
      "%LEMELY_SIDEBAR_WIDTH%",
    )
  })

  it("every resolved 252px declaration sits inside a min-width: 820px media query", () => {
    const filled = fillPreMountShell(REAL_INDEX_HTML)
    assertGated(filled, /252px/g, "@media (min-width: 820px)", "252px")
  })
})

/*
 * NIT (c): the tier 3 heading/body were hand-typed in index.html with nothing
 * pinning them to `FULL_PAGE_STATE_COPY["slow-load"]` in
 * `fullPageStateCopy.ts` — the source `scripts/check_copy.mjs` scans (`src/`
 * only, so index.html is invisible to it). This asserts word-for-word
 * agreement, and separately that the shell's own visible copy carries no
 * em-dash and no exclamation mark, matching REDESIGN-MISSION §3.2 item 10.
 */
describe("NIT (c): index.html's tier 3 copy matches FULL_PAGE_STATE_COPY[\"slow-load\"]", () => {
  const slowLoad = FULL_PAGE_STATE_COPY["slow-load"]

  // The body copy is hand-wrapped across two source lines in index.html for
  // readability (`...if you'd rather\n            start again.`), unlike the
  // one-line heading, so a plain substring `toContain` sees a newline and
  // indentation where the copy table has a single space. Collapsing
  // whitespace before comparing is the honest fix; reformatting index.html
  // onto one long line would trade this test's simplicity for the file's.
  const normalize = (s: string) => s.replace(/\s+/g, " ").trim()

  it("contains the slow-load heading verbatim", () => {
    expect(REAL_INDEX_HTML).toContain(slowLoad.heading)
  })

  it("contains the slow-load body verbatim (whitespace-normalized)", () => {
    const match = REAL_INDEX_HTML.match(/<p class="lm-shell-body-copy">([\s\S]*?)<\/p>/)
    expect(match?.[1]).toBeDefined()
    expect(normalize(match![1])).toBe(normalize(slowLoad.body))
  })

  it("the shell's visible text (heading, body, reload label) has no em-dash and no exclamation mark", () => {
    // "Visible text" = the tier 3 heading, body and reload label — the only
    // reader-facing prose the shell renders (everything else is decorative
    // skeleton bars with no text content). Extracted straight from the real
    // markup rather than from the copy table above, so this also catches a
    // future edit that types new tier 3 copy directly into index.html
    // without going through fullPageStateCopy.ts at all.
    const heading = REAL_INDEX_HTML.match(/<h1 class="lm-shell-heading">([\s\S]*?)<\/h1>/)
    const body = REAL_INDEX_HTML.match(/<p class="lm-shell-body-copy">([\s\S]*?)<\/p>/)
    const reload = REAL_INDEX_HTML.match(
      /<button type="button" class="lm-shell-reload"[^>]*>([\s\S]*?)<\/button>/,
    )
    expect(heading?.[1]).toBeDefined()
    expect(body?.[1]).toBeDefined()
    expect(reload?.[1]).toBeDefined()

    for (const match of [heading, body, reload]) {
      const text = match![1]
      expect(text).not.toMatch(/[—–]/)
      expect(text).not.toMatch(/!/)
    }
  })
})
