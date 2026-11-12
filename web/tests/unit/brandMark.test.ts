import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { tokenHex } from "../../vite/brandTokens"
import { stripComments } from "./support/jsxSource"

/**
 * The brand identity, as a gate (v5 Abyss, DESIGN.md "Logo: Clip Letters").
 *
 * Two renderers draw it and cannot share code: the inline `BrandLockup`
 * wordmark in React, and the standalone "lm" icon files in `public/brand/`
 * that the favicon link and `npm run icons` read. Three things can go wrong
 * there, and none of them is visible in a diff:
 *
 * 1. Somebody edits a curve in a generated file by hand; the next
 *    `npm run mark` silently reverts it.
 * 2. Somebody transcribes a colour into the generated files instead of letting
 *    `vite/brandTokens.ts` resolve it, and the icon stops tracking DESIGN.md.
 * 3. Somebody adds an animation to an SVG loaded through `<img>`, where the
 *    global `prefers-reduced-motion` block cannot reach it.
 */

const BRAND = join(import.meta.dirname, "..", "..", "public", "brand")
const read = (file: string): string => readFileSync(join(BRAND, file), "utf8")

const COLOUR = read("mark.svg")
const MONO = read("mark-mono.svg")
const FAVICON = read("mark-favicon.svg")

/** DESIGN.md "Logo: Clip Letters": the one clip path, written out in full. */
const DESIGN_MD_CLIP =
  "M58 34 V72 A8 8 0 0 1 42 72 V20 A14 14 0 0 1 70 20 V78 A18 18 0 0 1 34 78 V36"

describe("the generated 'lm' icon carries DESIGN.md's clip geometry", () => {
  it("the generator's clip is the path DESIGN.md prints", () => {
    // Read, not imported: importing the script would run it and rewrite the SVGs.
    const generator = readFileSync(join(import.meta.dirname, "..", "..", "scripts", "generate_mark_svg.mjs"), "utf8")
    expect(generator).toContain(DESIGN_MD_CLIP.replace(/ /g, " "))
    const design = readFileSync(join(import.meta.dirname, "..", "..", "..", "DESIGN.md"), "utf8")
    expect(design).toContain(DESIGN_MD_CLIP)
  })

  it.each(["mark.svg", "mark-favicon.svg", "mark-mono.svg"])(
    "%s draws that clip at stroke 5 with round caps and no fill",
    (file) => {
      const svg = read(file)
      expect(svg, `${file} is stale or hand-edited, run \`npm run mark\``).toContain(`d="${DESIGN_MD_CLIP}"`)
      const clip = svg.slice(svg.indexOf(`d="${DESIGN_MD_CLIP}"`)).split("/>")[0]
      expect(clip).toContain('stroke-width="5"')
      expect(clip).toContain('stroke-linecap="round"')
      expect(clip).toContain('fill="none"')
    },
  )

  it("the coloured cuts sit on a rounded square with rx 24 of 100", () => {
    for (const svg of [COLOUR, FAVICON]) {
      expect(svg).toContain('viewBox="0 0 100 100"')
      expect(svg).toMatch(/<rect width="100" height="100" rx="24"/)
    }
  })

  it("the favicon is the same drawing as mark.svg", () => {
    expect(FAVICON).toBe(COLOUR)
  })
})

describe("colour reaches the generated cuts through the tokens, never transcribed", () => {
  const ABYSS = tokenHex("md-primary")
  const TIDE = tokenHex("md-inverse-primary")
  const WHITE = tokenHex("md-on-primary")

  it("mark.svg paints only Abyss, Tide and white", () => {
    const painted = [...COLOUR.matchAll(/(?:fill|stroke)="(#[0-9A-Fa-f]{6})"/g)].map((m) => m[1])
    expect(painted.length).toBeGreaterThan(0)
    expect([...new Set(painted)].filter((hex) => ![ABYSS, TIDE, WHITE].includes(hex))).toEqual([])
  })

  it("the tile is Abyss, the clip is Tide and the m is white, as tokens resolve them", () => {
    expect(ABYSS).toBe("#042f4f")
    expect(TIDE).toBe("#7fb8e0")
    expect(WHITE).toBe("#ffffff")
    expect(COLOUR).toContain(`rx="24" fill="${ABYSS}"`)
    expect(COLOUR).toContain(`stroke="${TIDE}"`)
    expect(COLOUR).toContain(`stroke="${WHITE}"`)
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

describe("the inline Clip Letters wordmark (BrandLockup) follows DESIGN.md", () => {
  const lockup = stripComments(readFileSync(join(import.meta.dirname, "..", "..", "src", "components", "ui", "brand-lockup.tsx"), "utf8"))
  const CSS = readFileSync(join(import.meta.dirname, "..", "..", "src", "index.css"), "utf8")
  const letters = CSS.slice(CSS.indexOf(".wordmark-letters {"), CSS.indexOf("}", CSS.indexOf(".wordmark-letters {")))

  it("draws the clip from DESIGN.md's path at stroke 5, round caps, no fill", () => {
    expect(lockup).toContain(DESIGN_MD_CLIP)
    expect(lockup).toContain('viewBox="28 4 46 94"')
    expect(lockup).toContain('strokeWidth="5"')
    expect(lockup).toContain('strokeLinecap="round"')
    expect(lockup).toContain('fill="none"')
  })

  it("colours the clip with the primary role and the letters with on-surface", () => {
    expect(lockup).toContain("text-primary")
    expect(lockup).toContain('stroke="currentColor"')
    expect(lockup).toContain("wordmark-letters text-on-surface")
  })

  it("sets the letters in Bricolage 800 at line-height 0.82 and -0.04em tracking", () => {
    expect(letters).toMatch(/font:\s*800\s+var\(--wm-size[^)]*\)\s*\/\s*0\.82\s+var\(--font-display\)/)
    expect(letters).toMatch(/letter-spacing:\s*-0\.04em/)
  })

  it("never sizes the wordmark below DESIGN.md's 20px minimum height", () => {
    const sizes = [...CSS.matchAll(/\.wordmark-(?:sm|md)\s*\{\s*--wm-size:\s*(\d+)px/g)].map((m) => Number(m[1]))
    expect(sizes.length).toBe(2)
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(20)
  })
})
