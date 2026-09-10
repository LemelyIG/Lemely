import { describe, expect, it } from "vitest"
import { MASKABLE_SCALE, MAX_MASKABLE_SCALE, SQUARE_SCALE, tokenHex } from "../../vite/brandTokens.ts"

/*
 * Packet A5 — pins the icon-sizing constants `generate_icons.mjs` depends on,
 * now that they live in `vite/brandTokens.ts` rather than being declared
 * (and duplicated) inside the script itself. See that module's own
 * docstring for the safe-zone arithmetic `MAX_MASKABLE_SCALE` encodes.
 */

describe("MASKABLE_SCALE", () => {
  it("stays under the safe-zone ceiling, so the mark's corners survive an Android crop", () => {
    expect(MASKABLE_SCALE).toBeLessThanOrEqual(MAX_MASKABLE_SCALE)
  })

  it("MAX_MASKABLE_SCALE is exactly 0.8 / sqrt(2)", () => {
    expect(MAX_MASKABLE_SCALE).toBeCloseTo(0.8 / Math.SQRT2, 10)
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
