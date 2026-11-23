// web/tests/unit/masteryBar.test.ts
// a11y regression: the "learning" fill used `inverse-primary`, which is 1.16:1 against the
// track in dark and 1.79:1 in light, so the segment vanished. WCAG 1.4.11 wants >=3:1 for the
// graphic itself. Colours are read from the real token blocks in index.css, so a token edit
// that breaks a theme fails here instead of in a screenshot.
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { MasteryBar, MasteryLegend } from "@/portals/student/screens/flashcards/parts/MasteryBar"
import { masteryLegend, masteryView } from "@/portals/student/screens/flashcards/flashcardsView"

const SRC = join(import.meta.dirname, "..", "..", "src")
// Comments explain the choice and may name the rejected token; only code is asserted on.
const BAR_SOURCE = readFileSync(join(SRC, "portals/student/screens/flashcards/parts/MasteryBar.tsx"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
)
const CSS = readFileSync(join(SRC, "index.css"), "utf8")

const BLOCKS = {
  light: /^:root \{([\s\S]*?)\n\}/m.exec(CSS)?.[1] ?? "",
  dark: /^:root\[data-theme="dark"\] \{([\s\S]*?)\n\}/m.exec(CSS)?.[1] ?? "",
}

/** `--md-<name>` for a Tailwind colour utility `bg-<name>`, per theme (dark overrides light). */
function token(theme: "light" | "dark", name: string): string {
  const find = (block: string) => new RegExp(`--md-${name}:\\s*([^;]+);`).exec(block)?.[1]?.trim()
  const value = find(BLOCKS[theme]) ?? find(BLOCKS.light)
  if (!value) throw new Error(`no --md-${name} in ${theme}`)
  return value
}

function linearRgb(value: string): [number, number, number] {
  if (value.startsWith("#")) {
    const ch = [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16) / 255)
    return ch.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)) as [number, number, number]
  }
  const m = /oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/.exec(value)
  if (!m) throw new Error(`unparseable colour ${value}`)
  const [l, c, h] = [Number(m[1]), Number(m[2]), (Number(m[3]) * Math.PI) / 180]
  const a = c * Math.cos(h)
  const b = c * Math.sin(h)
  const l3 = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m3 = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s3 = (l - 0.0894841775 * a - 1.291485548 * b) ** 3
  const rgb = [
    4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
    -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
    -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3,
  ]
  return rgb.map((x) => Math.min(1, Math.max(0, x))) as [number, number, number]
}

const luminance = (value: string) => {
  const [r, g, b] = linearRgb(value)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const mastery = masteryView({ newCount: 3, learningCount: 3, knownCount: 4 })
const barHtml = renderToStaticMarkup(createElement(MasteryBar, { mastery }))
const fills = [...barHtml.matchAll(/<i class="([^"]*)" style="width:([\d.]+)%"/g)].map((m) => ({
  cls: m[1],
  token: /\bbg-([a-z-]+)/.exec(m[1])?.[1] ?? "",
}))
const [known, learning] = fills

describe("MasteryBar contrast", () => {
  it("renders a known and a learning fill from different tokens", () => {
    expect(fills).toHaveLength(2)
    expect(known.token).not.toBe("")
    expect(learning.token).not.toBe("")
    expect(learning.token).not.toBe(known.token)
  })

  it.each(["light", "dark"] as const)("keeps both fills at 3:1 or better against the track in %s", (theme) => {
    const track = token(theme, "surface-container-high")
    expect(contrast(token(theme, known.token), track), `known ${theme}`).toBeGreaterThanOrEqual(3)
    expect(contrast(token(theme, learning.token), track), `learning ${theme}`).toBeGreaterThanOrEqual(3)
  })

  it("never uses inverse-primary, which is a surface-inversion token and not a fill", () => {
    expect(BAR_SOURCE).not.toMatch(/inverse-primary/)
  })

  it("separates the segments with a track-coloured gap so no boundary depends on fill-to-fill contrast", () => {
    // Known (green) and learning cannot both clear 3:1 against the track and against each other
    // in dark (track lum .014, known .385), so the boundary is the track showing through.
    expect(barHtml).toMatch(/<div role="img"[^>]*class="[^"]*\bgap-0\.5\b/)
  })

  it("draws only the segments that have a share", () => {
    const onlyKnown = renderToStaticMarkup(
      createElement(MasteryBar, { mastery: masteryView({ newCount: 0, learningCount: 0, knownCount: 5 }) }),
    )
    expect(onlyKnown.match(/<i /g)).toHaveLength(1)
    const empty = renderToStaticMarkup(
      createElement(MasteryBar, { mastery: masteryView({ newCount: 0, learningCount: 0, knownCount: 0 }) }),
    )
    expect(empty.match(/<i /g)).toBeNull()
  })

  it("keeps the accessible name on the bar", () => {
    expect(barHtml).toContain('aria-label="4 known, 3 learning, 3 new"')
  })
})

describe("MasteryLegend", () => {
  const legend = masteryLegend(mastery)
  // Rendered per test, not at collection time, so a broken legend fails one case, not the suite.
  const render = () => renderToStaticMarkup(createElement(MasteryLegend, { legend }))
  const swatchesOf = (html: string) => [...html.matchAll(/<i aria-hidden="true" class="([^"]*)"/g)].map((m) => m[1])

  it("builds structured items instead of strings to be split", () => {
    expect(legend).toEqual([
      { key: "known", count: 4, label: "known" },
      { key: "learning", count: 3, label: "learning" },
      { key: "new", count: 3, label: "new" },
    ])
    expect(BAR_SOURCE).not.toMatch(/\.split\(/)
  })

  it("matches the bar: the known and learning swatches use the fills' own tokens", () => {
    const swatches = swatchesOf(render())
    expect(swatches).toHaveLength(3)
    expect(swatches[0]).toContain(`bg-${known.token}`)
    expect(swatches[1]).toContain(`bg-${learning.token}`)
    expect(swatches[2]).toContain("bg-surface-container-high")
  })

  it("sets each count in mono and its label as plain text", () => {
    const html = render()
    expect(html).toMatch(/<span class="font-mono">4<\/span>(<!-- -->)? ?(<!-- -->)?known/)
    expect(html).toMatch(/<span class="font-mono">3<\/span>(<!-- -->)? ?(<!-- -->)?learning/)
  })

  it("keeps a zero count readable", () => {
    const zero = renderToStaticMarkup(
      createElement(MasteryLegend, { legend: masteryLegend(masteryView({ newCount: 0, learningCount: 0, knownCount: 2 })) }),
    )
    expect(zero).toMatch(/<span class="font-mono">0<\/span>(<!-- -->)? ?(<!-- -->)?learning/)
  })
})
