import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { COIL, LEFT_FACE, RIGHT_FACE, STACK_EDGES, type MarkPath } from "../../src/lib/brandMark"
import { tokenHex } from "../../vite/brandTokens"

/**
 * The brand mark, as a gate.
 *
 * The mark is drawn twice by two renderers that cannot share code — inline in
 * `components/ui/brand-mark.tsx`, and as standalone files in `public/brand/` —
 * and it animates in one of them and must not in the other. Three things can go
 * wrong there, and none of them is visible in a diff:
 *
 * 1. Somebody edits a curve in `public/brand/mark.svg` by hand. It is a
 *    generated file, so the next `npm run mark` silently reverts them, and in
 *    the meantime the favicon and the header show different marks.
 * 2. Somebody transcribes a colour into the generated files instead of letting
 *    `vite/brandTokens.ts` resolve it, and the mark stops tracking DESIGN.md.
 * 3. Somebody adds the animation back into `mark.svg`, where it looks correct
 *    and cannot be switched off. That is the whole finding this redesign turns
 *    on: an SVG in an `<img>` is a separate document, index.css's global
 *    reduced-motion block cannot reach it, and Chromium does not propagate
 *    `prefers-reduced-motion` into an SVG-as-image either — measured, with a
 *    probe SVG whose fill changes under the query and an `<img>` on a page
 *    whose own `matchMedia` for it returns true. A media query written inside
 *    the file would be a rule with no reader, and the logo would move in every
 *    header for a reader who had asked it not to.
 *
 * `mark-favicon.svg` is deliberately absent from the drift checks: it is a
 * hand-authored optical cut for 16x16, a different drawing rather than a
 * different rendering, and its own comment says which features of the parent it
 * drops and why each measurably fails at four viewBox units per device pixel.
 * It is still checked for animation, because the reasoning about `<img>` is the
 * same wherever the file is loaded.
 */

const BRAND = join(import.meta.dirname, "..", "..", "public", "brand")
const read = (file: string): string => readFileSync(join(BRAND, file), "utf8")

const COLOUR = read("mark.svg")
const MONO = read("mark-mono.svg")
const FAVICON = read("mark-favicon.svg")

const ALL_PATHS: MarkPath[] = [...STACK_EDGES, ...LEFT_FACE, ...RIGHT_FACE, ...COIL]

/** The `d` attribute as the generator writes it: whitespace collapsed. */
const compact = (d: string): string => d.replace(/\s+/g, " ").trim()

describe("the generated mark cuts carry the geometry module's coordinates", () => {
  it.each(["mark.svg", "mark-mono.svg"])("%s has every path from lib/brandMark.ts", (file) => {
    const svg = read(file)
    const missing = ALL_PATHS.map((path) => compact(path.d)).filter((d) => !svg.includes(d))
    expect(missing, `${file} is stale or hand-edited — run \`npm run mark\``).toEqual([])
  })

  it.each(["mark.svg", "mark-mono.svg"])("%s has no path the module does not define", (file) => {
    const known = new Set(ALL_PATHS.map((path) => compact(path.d)))
    const drawn = [...read(file).matchAll(/<path d="([^"]+)"/g)].map((match) => match[1])
    // The stack edges are drawn twice — once per page — which is the only
    // path in the mark that appears more than once in a cut.
    expect(drawn.length).toBe(ALL_PATHS.length + STACK_EDGES.length)
    expect(drawn.filter((d) => !known.has(d))).toEqual([])
  })
})

describe("colour reaches the generated cuts through the tokens, never transcribed", () => {
  it("mark.svg paints only DESIGN.md token values", () => {
    const allowed = new Set(
      ALL_PATHS.flatMap(({ fill, stroke }) => [fill, stroke])
        .filter((token) => token !== "none")
        .map((token) => tokenHex(token)),
    )
    const painted = [...COLOUR.matchAll(/(?:fill|stroke)="(#[0-9A-Fa-f]{6})"/g)].map((m) => m[1])
    expect(painted.length).toBeGreaterThan(0)
    expect([...new Set(painted)].filter((hex) => !allowed.has(hex))).toEqual([])
  })

  it("the accent and the ink in mark.svg are the tokens, not a near miss", () => {
    expect(COLOUR).toContain(`stroke="${tokenHex("accent")}"`)
    expect(COLOUR).toContain(`stroke="${tokenHex("ink")}"`)
  })

  it("mark-mono.svg is one colour and it is the caller's", () => {
    expect(MONO).not.toMatch(/#[0-9A-Fa-f]{6}/)
    expect(MONO).toContain('stroke="currentColor"')
    expect(MONO).not.toMatch(/fill="(?!none")/)
  })
})

describe("the standalone cuts do not animate, because they could not be stopped", () => {
  it.each([
    ["mark.svg", COLOUR],
    ["mark-mono.svg", MONO],
    ["mark-favicon.svg", FAVICON],
  ])("%s declares no animation", (_file, svg) => {
    // Comments explain why there is none, so strip them before looking.
    const markup = svg.replace(/<!--[\s\S]*?-->/g, "")
    expect(markup).not.toMatch(/@keyframes|animation|<animate|<style/i)
  })
})

describe("the inline mark's motion obeys §9.2 and can be reduced", () => {
  const CSS = readFileSync(join(import.meta.dirname, "..", "..", "src", "index.css"), "utf8")
  const turn = CSS.slice(
    CSS.indexOf("/* ── The brand mark's page turn"),
    CSS.indexOf("/* ── §9.3 The celebration register"),
  ).replace(/\/\*[\s\S]*?\*\//g, "")

  it("is present in index.css, where the global reduced-motion block reaches it", () => {
    expect(turn).toContain("@keyframes lm-leaf-front")
    expect(turn).toContain("@keyframes lm-leaf-back")
  })

  it("animates transform and opacity and nothing else", () => {
    const properties = [...turn.matchAll(/^\s*([a-z-]+)\s*:/gm)].map((match) => match[1])
    const animatable = properties.filter(
      (property) => !property.startsWith("animation") && !property.startsWith("transform"),
    )
    expect([...new Set(animatable)].filter((p) => !["opacity", "display"].includes(p))).toEqual([])
  })

  it("names a §9.1 easing rather than inheriting a browser default", () => {
    expect(turn).toMatch(/animation-timing-function:\s*var\(--ease-in-soft\)/)
    expect(turn).toMatch(/animation-timing-function:\s*var\(--ease-out-soft\)/)
  })
})
