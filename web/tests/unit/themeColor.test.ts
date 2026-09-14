import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { fillThemeColor } from "../../vite/themeColor.ts"

/*
 * `vite/themeColor.ts`'s placeholder plugin (P6.5), extended by Task 13
 * (C5b) with a second, dark placeholder — exercised as a pure function
 * (`fillThemeColor`), the same `fillPreMountShell` pattern
 * `preMountShell.test.ts` uses, so a broken substitution fails a unit test
 * rather than only showing up as a literal `%LEMELY_THEME_COLOR_DARK%`
 * string painted in a mobile browser's chrome.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const REAL_INDEX_HTML = readFileSync(join(ROOT, "index.html"), "utf8")

describe("fillThemeColor", () => {
  it("resolves both placeholders to distinct 6-digit hex colours", () => {
    const filled = fillThemeColor(REAL_INDEX_HTML)
    const contentMatch = filled.match(/name="theme-color"\s+content="(#[0-9a-f]{6})"/)
    const lightMatch = filled.match(/data-theme-light="(#[0-9a-f]{6})"/)
    const darkMatch = filled.match(/data-theme-dark="(#[0-9a-f]{6})"/)

    expect(contentMatch?.[1]).toBeDefined()
    expect(lightMatch?.[1]).toBeDefined()
    expect(darkMatch?.[1]).toBeDefined()

    // content mirrors the light value (the meta's initial paint, before
    // shell-init.js/applyTheme.ts might swap it to dark).
    expect(contentMatch![1]).toBe(lightMatch![1])
    // The two resolved paper tones must actually differ — a build that
    // silently resolved the dark placeholder to the light token again would
    // pass every "is this a hex colour" check and still be wrong.
    expect(darkMatch![1]).not.toBe(lightMatch![1])
  })

  it("leaves no %LEMELY_THEME_COLOR...% placeholder in the resolved real index.html", () => {
    const filled = fillThemeColor(REAL_INDEX_HTML)
    expect(filled).not.toMatch(/%LEMELY_THEME_COLOR[A-Z_]*%/)
  })

  it("throws, naming it, when the light placeholder is missing", () => {
    const without = REAL_INDEX_HTML.replaceAll("%LEMELY_THEME_COLOR%", "")
    expect(() => fillThemeColor(without)).toThrow(/LEMELY_THEME_COLOR/)
  })

  it("throws, naming it, when the dark placeholder is missing", () => {
    const without = REAL_INDEX_HTML.replaceAll("%LEMELY_THEME_COLOR_DARK%", "")
    expect(() => fillThemeColor(without)).toThrow(/LEMELY_THEME_COLOR_DARK/)
  })
})
