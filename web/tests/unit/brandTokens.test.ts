import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { tokenHex } from "../../vite/brandTokens.ts"
import { MASKABLE_SCALE, SQUARE_SCALE, maxMaskableScale, measureDrawnExtent } from "../../vite/iconSafeZone.ts"

/*
 * Packet A5 — pins the icon-sizing constants `generate_icons.mjs` depends on.
 * `SQUARE_SCALE`/`MASKABLE_SCALE` live in `vite/iconSafeZone.ts` rather than
 * being declared (and duplicated) inside the script itself; the maskable
 * ceiling is measured against the real mark SVG here, not assumed, because
 * the mark's artboard is not square (see that module's own docstring).
 */

const MARK = fileURLToPath(new URL("../../public/brand/mark.svg", import.meta.url))

describe("MASKABLE_SCALE", () => {
  it("stays under the safe-zone ceiling for the real mark, so its corners survive an Android crop", async () => {
    const extent = await measureDrawnExtent(readFileSync(MARK))
    expect(MASKABLE_SCALE).toBeLessThanOrEqual(maxMaskableScale(extent))
  })
})

describe("SQUARE_SCALE", () => {
  it("is a fraction of the icon's width, strictly between 0 and 1", () => {
    expect(SQUARE_SCALE).toBeGreaterThan(0)
    expect(SQUARE_SCALE).toBeLessThan(1)
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
