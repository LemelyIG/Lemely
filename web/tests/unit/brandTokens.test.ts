import { fileURLToPath } from "node:url"
import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { CLIP_PATH, M_PATH, appIconContent } from "../../vite/appIcon.ts"
import { tokenHex } from "../../vite/brandTokens.ts"
import { MASKABLE_SCALE, maxMaskableScale, measureDrawnBounds } from "../../vite/iconSafeZone.ts"

/*
 * Pins the icon constants `generate_icons.mjs` depends on. The maskable ceiling
 * is measured against the real app icon artwork (clip and "m", `vite/appIcon.ts`),
 * not assumed, because the artwork is neither square nor centred on its artboard.
 */

const CONTENT_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">${appIconContent()}</svg>`
const FAVICON = fileURLToPath(new URL("../../public/brand/mark-favicon.svg", import.meta.url))

describe("MASKABLE_SCALE", () => {
  it("stays under the safe-zone ceiling for the real icon, so its corners survive an Android crop", async () => {
    const bounds = await measureDrawnBounds(Buffer.from(CONTENT_SVG))
    expect(MASKABLE_SCALE).toBeGreaterThan(0)
    expect(MASKABLE_SCALE).toBeLessThanOrEqual(maxMaskableScale(bounds))
  })
})

describe("app icon artwork", () => {
  it("keeps the brand-guideline clip geometry and draws the m as an outline, not text", () => {
    expect(CLIP_PATH).toBe("M58 34 V72 A8 8 0 0 1 42 72 V20 A14 14 0 0 1 70 20 V78 A18 18 0 0 1 34 78 V36")
    expect(M_PATH.startsWith("M")).toBe(true)
    expect(appIconContent()).not.toContain("<text")
    expect(appIconContent()).toContain('stroke-width="5"')
  })

  it("ships a favicon.svg with the same clip, m and Abyss field, and no font dependency", () => {
    const svg = readFileSync(FAVICON, "utf8")
    expect(svg).toContain(CLIP_PATH)
    expect(svg).toContain(M_PATH)
    expect(svg).toContain("#042f4f")
    expect(svg).not.toContain("font-family")
  })
})

describe("tokenHex", () => {
  it("resolves --paper to a real 6-digit hex colour", () => {
    expect(tokenHex("paper")).toMatch(/^#[0-9a-f]{6}$/)
  })

  it("throws on a token that isn't declared as oklch() in :root", () => {
    expect(() => tokenHex("definitely-not-a-real-token")).toThrow(/not declared as an oklch/)
  })
})
