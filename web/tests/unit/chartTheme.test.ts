import { readFileSync, readdirSync } from "node:fs"
import { join, relative as pathRelative } from "node:path"
import { describe, expect, it } from "vitest"
import {
  CHART_TOKENS,
  SERIES_TOKENS,
  SINGLE_SERIES_TOKEN,
  buildNivoTheme,
  resolveChartTokens,
} from "@/lib/nivoTheme"

/**
 * The chart-theme gate (P5.3).
 *
 * Charts introduce a *new instance of the one defect shape this build keeps
 * being caught by*, and it is worth being precise about why, because the
 * existing gates cannot see it.
 *
 * A colour reaches a Nivo chart as a plain string. `@nivo/line` hands series
 * colours to react-spring (`useSpring({ color })`) so it can interpolate them
 * across a transition, and react-spring *parses* the string as a colour before
 * it ever reaches the DOM. `var(--accent)` is not a parseable colour. One level
 * lower, the same is true without react-spring: CSS custom properties are not
 * substituted inside SVG presentation attributes, so `stroke="var(--accent)"`
 * resolves to nothing too.
 *
 * So the natural, token-disciplined-looking thing to write here — passing
 * `var(--accent)` to a chart, exactly as every other component in this product
 * correctly does through a Tailwind class — produces a chart drawn in nothing,
 * or in whatever a colour parser makes of an unrecognised token. It would pass
 * typecheck, lint, the token gate (there is no raw value to find), and
 * `utilityExistence` (there is no class name to check). It is `--font-serif`
 * (D4.1), `text-display` (D4.4), `lm-head` (D4.5) and the banned easing (D4.6),
 * arriving a fifth time by a route none of those four gates watch.
 *
 * `nivoTheme.ts` therefore resolves tokens from the document at runtime, and
 * this file gates the two things that can silently break that:
 *
 *   1. a token named here but not defined in `index.css` (a rename, a typo, a
 *      token retired by a later phase), and
 *   2. a `var()` string creeping back into the theme or a chart component.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const INDEX_CSS = readFileSync(join(ROOT, "src", "index.css"), "utf8")

const CHART_SOURCES = [
  "src/lib/nivoTheme.ts",
  "src/components/ui/line-chart.tsx",
  "src/components/ui/bar-chart.tsx",
]

function sourceOf(relative: string): string {
  return readFileSync(join(ROOT, relative), "utf8")
}

/** A repo-relative path with forward slashes, for comparison against the list. */
function relativeTo(absolute: string): string {
  return pathRelative(ROOT, absolute).split("\\").join("/")
}

/** True when `index.css` declares `name` as a custom property on some rule. */
function isDefinedInCss(name: string): boolean {
  // `--foo:` at the start of a declaration. Anchored to a line start plus
  // whitespace so `--color-foo: var(--foo)` in the `@theme` block cannot be
  // mistaken for a definition of `--foo` itself.
  return new RegExp(`^\\s*${name.replace(/-/g, "\\-")}\\s*:`, "m").test(INDEX_CSS)
}

describe("chart tokens exist", () => {
  it("names at least the six series colours plus the single-series accent", () => {
    expect(SERIES_TOKENS).toHaveLength(6)
    expect(CHART_TOKENS.length).toBeGreaterThanOrEqual(7)
  })

  it.each(CHART_TOKENS)("`%s` is defined in index.css", (token) => {
    expect(isDefinedInCss(token)).toBe(true)
  })

  it("keeps DESIGN.md §11's series order: sky, sage, amber, clay, lilac, rose", () => {
    expect([...SERIES_TOKENS]).toEqual([
      "--pastel-sky-ink",
      "--pastel-sage-ink",
      "--pastel-amber-ink",
      "--pastel-clay-ink",
      "--pastel-lilac-ink",
      "--pastel-rose-ink",
    ])
  })

  it("draws series in the -ink half of each pastel pair, never the wash", () => {
    // The wash sits at L≈0.94 against a paper surface at L≈0.99. A 2px line in
    // it is, for practical purposes, not on the screen. This is the assertion
    // that stops someone "fixing" the theme to match §11's hue names literally.
    for (const token of SERIES_TOKENS) {
      expect(token.endsWith("-ink")).toBe(true)
    }
  })

  it("keeps the accent out of the categorical series", () => {
    // §11: accent means "the teacher's mark" everywhere else in this product.
    // It is the single-series colour and must never become "series 1".
    expect(SERIES_TOKENS as readonly string[]).not.toContain(SINGLE_SERIES_TOKEN)
    expect(SINGLE_SERIES_TOKEN).toBe("--accent")
  })
})

describe("chart colours are never CSS variable strings", () => {
  it.each(CHART_SOURCES)("%s passes no `var(--...)` to a chart", (relative) => {
    const source = sourceOf(relative)
    // Comments in these files discuss `var(--accent)` at length, and rightly:
    // the reasoning is the point. Strip them before looking for real usage.
    const code = source
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "")
    expect(code).not.toMatch(/var\(\s*--/)
  })

  it.each(CHART_SOURCES)("%s hardcodes no colour literal", (relative) => {
    const code = sourceOf(relative)
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "")
    // Hex, oklch, rgb and hsl. The one permitted exception is the tooltip's
    // ultra-diffuse shadow, which §3.2 item 5 specifies as an opacity on black
    // rather than as a token, so it is matched and allowed by name.
    const withoutShadow = code.replace(/0 4px 16px rgba\(0,0,0,0\.05\)/g, "")
    expect(withoutShadow).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(withoutShadow).not.toMatch(/\b(oklch|rgba?|hsla?)\s*\(/)
  })
})

describe("the theme fails closed", () => {
  it("resolves every token to an empty string with no document", () => {
    // The node test environment has no `window`, which is the same position a
    // chart is in on its very first render. Nothing here may throw.
    const tokens = resolveChartTokens()
    expect(Object.keys(tokens).sort()).toEqual([...CHART_TOKENS].sort())
    expect(Object.values(tokens).every((v) => v === "")).toBe(true)
  })

  it("builds a theme from empty tokens without throwing", () => {
    // `useNivoTheme` gates rendering on `ready`, but `buildNivoTheme` is called
    // unconditionally on every render including the first, so it has to survive
    // the un-resolved case rather than being protected from it.
    expect(() => buildNivoTheme({})).not.toThrow()
  })

  it("sets the data face and horizontal-only grid §11 specifies", () => {
    const theme = buildNivoTheme(resolveChartTokens())
    expect(theme.background).toBe("transparent")
    expect(theme.grid?.line).toBeDefined()
    expect(theme.tooltip?.container).toBeDefined()
  })
})

describe("every chart goes through the shared wrappers", () => {
  it("has no direct @nivo import outside the two wrappers and the theme", () => {
    /*
     * The whole point of §11's "no chart sets its own colours" is that there is
     * exactly one place a chart can be configured. A screen importing
     * `ResponsiveLine` directly would bypass the theme, the reduced-motion
     * path, the token-readiness gate and the focusable points in one go.
     *
     * **This walks the tree rather than reading a list of files.** P4.10's
     * finding was that the three existing gate lists only grow by hand, so a
     * screen no surface claims is a screen no gate reads — which is how the
     * whole of onboarding sat in the build-era language for the entire
     * redesign. A gate written this phase should not add a fourth list to
     * forget to update. Anything under `src/` is in scope the moment it exists.
     */
    const offenders: string[] = []

    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) {
          walk(full)
        } else if (/\.tsx?$/.test(entry.name)) {
          const relative = relativeTo(full)
          if (CHART_SOURCES.includes(relative)) continue
          if (/from "@nivo\//.test(readFileSync(full, "utf8"))) offenders.push(relative)
        }
      }
    }
    walk(join(ROOT, "src"))

    expect(offenders).toEqual([])
  })
})
