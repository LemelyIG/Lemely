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
  it("resolves --md-surface to a real 6-digit hex colour", () => {
    expect(tokenHex("md-surface")).toMatch(/^#[0-9a-f]{6}$/)
  })

  it("throws on a token that isn't declared as oklch() in :root", () => {
    expect(() => tokenHex("definitely-not-a-real-token")).toThrow(/not declared as an oklch/)
  })
})

describe("marketing brand-tokens.css", () => {
  const css = readFileSync(fileURLToPath(new URL("../../src/portals/marketing/brand-tokens.css", import.meta.url)), "utf8")
  const code = css.replace(/\/\*[\s\S]*?\*\//g, "")

  it("holds no colour literal, so the Material 3 roles stay the one source", () => {
    expect(code).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(code).not.toMatch(/oklch\(/)
  })

  it("has no @theme block that could override the global utilities", () => {
    expect(code).not.toMatch(/@theme/)
    expect(code).not.toMatch(/--color-/)
  })

  it.each(["background", "foreground", "primary", "primary-foreground", "secondary-foreground", "muted", "muted-foreground", "ring", "border"])(
    "resolves --%s to a --md- role",
    (name) => {
      const m = code.match(new RegExp(`^\\s*--${name}:\\s*([^;]+);`, "m"))
      expect(m?.[1]).toMatch(/^var\(--md-[a-z-]+\)$/)
    },
  )
})
